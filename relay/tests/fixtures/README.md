Model helpers are deterministic fixtures with no network. evidence-run.sh and
backup-worktree.sh are snapshots of osslab-manager at Brain commit
3557ac100f8425efd20704e1eae97264a85473e7, retained to test the existing helper
contract without a Brain installation. They are test data, never runtime routes.

real-pi/ holds a snapshot of the real osslab-manager pi worker (RunInfra default, OpenRouter kept), its RPC
driver, the ask_manager extension and its templates (Brain branch feat/osslab-manager-worker-ask). The
integration tests run it with a fake RPC `pi` on PATH and a throwaway HOME, so the session contract and the
v1.3 question channel between Relay, the real helper and the real driver are exercised without a model call.

fake-paseo-cli/ stands in for the two Paseo CLI modules the v1.4 wake helper imports (`dist/utils/client.js`,
`dist/utils/daemon-target.js`), so the helper's decisions run under node without a Paseo daemon.
