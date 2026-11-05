# ABOUTME: The no-cloud guard (verify/no-cloud.sh) for an offline Python test run by hand (#859): every subprocess
# ABOUTME: it starts gets the stubbed cloud tools first on PATH and no credentials, and calls() is the call log.
"""No-cloud guard for an offline Python test that runs fleet.sh.

no-cloud.sh says why, and writes the stubs: setup() runs its no_cloud_setup and reads its NO_CLOUD_UNSET, so the tool
list, the stub text and the variables cleared have one source. setup() then does in os.environ what no_cloud_guard
does in a shell: the stubs first on PATH and the cloud variables cleared, so every subprocess that inherits the
environment, or copies PATH from it, reaches the stubs and no credentials.

    import no_cloud  # noqa: E402
    no_cloud.setup()
    ...
    check("no check above called aws, kubectl, eksctl, terraform or helm", not no_cloud.calls())
"""
import atexit
import os
import pathlib
import shutil
import subprocess
import tempfile

NO_CLOUD_SH = pathlib.Path(__file__).resolve().parent / "no-cloud.sh"
LOG: pathlib.Path | None = None


def setup(directory: str | os.PathLike | None = None) -> pathlib.Path:
    """Write the stubs, put them first on PATH and return the call log. With no directory, a temp one removed at exit."""
    global LOG
    if directory is None:
        directory = tempfile.mkdtemp(prefix="no-cloud-")
        atexit.register(shutil.rmtree, directory, True)
    d = pathlib.Path(directory)
    unset = subprocess.run(["bash", "-c", '. "$1" && no_cloud_setup "$2" && printf "%s\\n" "${NO_CLOUD_UNSET[@]}"',
                            "_", str(NO_CLOUD_SH), str(d)], check=True, capture_output=True, text=True).stdout.split()
    if not unset:
        raise RuntimeError(f"{NO_CLOUD_SH} names no NO_CLOUD_UNSET variables, so the guard is not in place")
    for v in unset:
        os.environ.pop(v, None)
    LOG = d / "cloud-calls"
    os.environ.update(KUBECONFIG=str(d / "no-kubeconfig"), AWS_CONFIG_FILE=str(d / "no-aws-config"),
                      AWS_SHARED_CREDENTIALS_FILE=str(d / "no-aws-credentials"), AWS_EC2_METADATA_DISABLED="true",
                      PATH=f"{d / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    return LOG


def calls() -> str:
    """The stubbed-tool calls made since setup(), one per line; empty when there were none."""
    if LOG is None:
        raise RuntimeError("no_cloud.setup() has not run, so the guard is not in place")
    return LOG.read_text() if LOG.exists() else ""
