// Replays one Argo CD v3.5.2 sync of one resource against a real kube-apiserver (#679), with Argo CD's own code.
//
//	argo-sync-replay norm  <in.json>                                      the target a sync applies
//	argo-sync-replay diff  <kubeconfig> <target.json> <live.json> <ignores.json>  Synced or OutOfSync
//
// norm is controller/sync.go's normalizeTargetResources for one resource, copied from v3.5.2 (getMergePatch,
// applyMergePatch and restoreNonIgnoredFields verbatim), with the ignored fields deleted the way Argo CD's ignore
// normalizer does it: gojq del(<expression>). Its input is {"target": {...}, "live": {...}, "exprs": [...]}.
//
// diff is util/argo/diff.StateDiff from the argo-cd v3.5.2 module itself, configured as controller/state.go configures
// an Application that syncs with ServerSideApply=true: structured merge diff, manager argocd-controller, the GVK
// parser built from the apiserver's OpenAPI. Its ignores file is the Application's ignoreDifferences as JSON.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"

	"github.com/argoproj/argo-cd/v3/pkg/apis/application/v1alpha1"
	argodiff "github.com/argoproj/argo-cd/v3/util/argo/diff"
	"github.com/argoproj/argo-cd/v3/util/argo/normalizers"
	jsonpatch "github.com/evanphx/json-patch"
	"github.com/itchyny/gojq"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/util/managedfields"
	"k8s.io/apimachinery/pkg/util/strategicpatch"
	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/kube-openapi/pkg/util/proto"
)

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "argo-sync-replay:", err)
		os.Exit(2)
	}
}

func load(p string) map[string]any {
	b, err := os.ReadFile(p)
	must(err)
	var m map[string]any
	must(json.Unmarshal(b, &m))
	return m
}

func deepcopy(m map[string]any) map[string]any {
	b, _ := json.Marshal(m)
	var out map[string]any
	_ = json.Unmarshal(b, &out)
	return out
}

// jqDel is the ignore normalizer's jq patch: del(<expression>), and an expression that errors leaves the object.
func jqDel(obj map[string]any, exprs []string) map[string]any {
	for _, e := range exprs {
		q, err := gojq.Parse(fmt.Sprintf("del(%s)", e))
		must(err)
		code, err := gojq.Compile(q)
		must(err)
		v, ok := code.Run(obj).Next()
		if !ok {
			continue
		}
		if _, isErr := v.(error); isErr {
			continue
		}
		obj = v.(map[string]any)
	}
	return obj
}

// ---- controller/sync.go v3.5.2, verbatim ------------------------------------------------------------------------

func getMergePatch(original, modified *unstructured.Unstructured, lookupPatchMeta *strategicpatch.PatchMetaFromStruct) ([]byte, error) {
	originalJSON, err := original.MarshalJSON()
	if err != nil {
		return nil, err
	}
	modifiedJSON, err := modified.MarshalJSON()
	if err != nil {
		return nil, err
	}
	if lookupPatchMeta != nil {
		return strategicpatch.CreateThreeWayMergePatch(modifiedJSON, modifiedJSON, originalJSON, lookupPatchMeta, true)
	}

	return jsonpatch.CreateMergePatch(originalJSON, modifiedJSON)
}

func applyMergePatch(obj *unstructured.Unstructured, patch []byte, versionedObject any) (*unstructured.Unstructured, error) {
	originalJSON, err := obj.MarshalJSON()
	if err != nil {
		return nil, err
	}
	var patchedJSON []byte
	if versionedObject == nil {
		patchedJSON, err = jsonpatch.MergePatch(originalJSON, patch)
	} else {
		patchedJSON, err = strategicpatch.StrategicMergePatch(originalJSON, patch, versionedObject)
	}
	if err != nil {
		return nil, err
	}

	patchedObj := &unstructured.Unstructured{}
	_, _, err = unstructured.UnstructuredJSONScheme.Decode(patchedJSON, nil, patchedObj)
	if err != nil {
		return nil, err
	}
	return patchedObj, nil
}

func restoreNonIgnoredFields(patched, original, normalizedTarget, normalizedLive map[string]any) {
	for key, originalVal := range original {
		patchedVal, inPatched := patched[key]
		normalizedVal, inNormalized := normalizedTarget[key]

		patchedMap, patchedIsMap := patchedVal.(map[string]any)
		originalMap, originalIsMap := originalVal.(map[string]any)
		normalizedMap, normalizedIsMap := normalizedVal.(map[string]any)

		if inPatched && patchedIsMap && originalIsMap && normalizedIsMap {
			var normalizedLiveMap map[string]any
			if v, ok := normalizedLive[key].(map[string]any); ok {
				normalizedLiveMap = v
			}
			restoreNonIgnoredFields(patchedMap, originalMap, normalizedMap, normalizedLiveMap)
			continue
		}

		if inNormalized && reflect.DeepEqual(normalizedVal, originalVal) && (!inPatched || !reflect.DeepEqual(patchedVal, originalVal)) {
			patched[key] = originalVal
		}
	}

	for key := range patched {
		if _, inOriginal := original[key]; inOriginal {
			continue
		}
		if _, inNormalizedLive := normalizedLive[key]; inNormalizedLive {
			delete(patched, key)
		}
	}
}

// norm is the loop body of normalizeTargetResources for one live resource.
func norm(target, live map[string]any, exprs []string) map[string]any {
	originalTarget := &unstructured.Unstructured{Object: target}
	normalizedTarget := &unstructured.Unstructured{Object: jqDel(deepcopy(target), exprs)}
	liveObj := &unstructured.Unstructured{Object: live}
	normalizedLive := &unstructured.Unstructured{Object: jqDel(deepcopy(live), exprs)}

	var lookupPatchMeta *strategicpatch.PatchMetaFromStruct
	var versionedObject any
	if vo, err := scheme.Scheme.New(normalizedTarget.GroupVersionKind()); err == nil {
		meta, err := strategicpatch.NewPatchMetaFromStruct(vo)
		must(err)
		lookupPatchMeta = &meta
		versionedObject = vo
	}

	liveForPatch := liveObj.DeepCopy()
	unstructured.RemoveNestedField(liveForPatch.Object, "status")
	normalizedLiveForPatch := normalizedLive.DeepCopy()
	unstructured.RemoveNestedField(normalizedLiveForPatch.Object, "status")

	livePatch, err := getMergePatch(normalizedLiveForPatch, liveForPatch, lookupPatchMeta)
	must(err)
	patchedTarget, err := applyMergePatch(normalizedTarget, livePatch, versionedObject)
	must(err)
	restoreNonIgnoredFields(patchedTarget.Object, originalTarget.Object, normalizedTarget.Object, normalizedLive.Object)
	return patchedTarget.Object
}

func diff(kubeconfig, targetPath, livePath, ignoresPath string) bool {
	cfg, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
	must(err)
	doc, err := discovery.NewDiscoveryClientForConfigOrDie(cfg).OpenAPISchema()
	must(err)
	models, err := proto.NewOpenAPIData(doc)
	must(err)
	parser, err := managedfields.NewGVKParser(models, false)
	must(err)
	var ignores []v1alpha1.ResourceIgnoreDifferences
	b, err := os.ReadFile(ignoresPath)
	must(err)
	must(json.Unmarshal(b, &ignores))
	dcfg, err := argodiff.NewDiffConfigBuilder().
		WithDiffSettings(ignores, map[string]v1alpha1.ResourceOverride{}, false, normalizers.IgnoreNormalizerOpts{}).
		WithTracking("app.kubernetes.io/instance", "annotation").
		WithNoCache().
		WithGVKParser(parser).
		WithManager("argocd-controller").
		WithStructuredMergeDiff(true).
		Build()
	must(err)
	res, err := argodiff.StateDiff(&unstructured.Unstructured{Object: load(livePath)},
		&unstructured.Unstructured{Object: load(targetPath)}, dcfg)
	must(err)
	return res.Modified
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "norm" {
		var in struct {
			Target map[string]any `json:"target"`
			Live   map[string]any `json:"live"`
			Exprs  []string       `json:"exprs"`
		}
		b, err := os.ReadFile(os.Args[2])
		must(err)
		must(json.Unmarshal(b, &in))
		out, err := json.Marshal(norm(in.Target, in.Live, in.Exprs))
		must(err)
		fmt.Println(string(out))
		return
	}
	if len(os.Args) == 6 && os.Args[1] == "diff" {
		if diff(os.Args[2], os.Args[3], os.Args[4], os.Args[5]) {
			fmt.Println("OutOfSync")
		} else {
			fmt.Println("Synced")
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: argo-sync-replay norm <in.json> | diff <kubeconfig> <target.json> <live.json> <ignores.json>")
	os.Exit(2)
}
