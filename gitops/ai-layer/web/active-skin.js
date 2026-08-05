// ABOUTME: THE skin knob. One line. Set this to any key defined in skins.js to reskin the VTT chrome.
// ABOUTME: Roll back by setting it to "burritobot". Live cluster: delete the console pod after changing it.
//
// Fresh clusters pick up whatever is set here at provision. On an already-running cluster, the console
// ConfigMap has a fixed name (no content hash), so bounce the pod to apply:
//   kubectl -n agent delete pod -l app.kubernetes.io/name=console
window.WITB_ACTIVE_SKIN = "burritobot";
