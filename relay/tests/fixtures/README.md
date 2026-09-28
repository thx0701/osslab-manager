Model helpers are deterministic fixtures with no network. evidence-run.sh and
backup-worktree.sh are snapshots of osslab-manager at Brain commit
3557ac100f8425efd20704e1eae97264a85473e7, retained to test the existing helper
contract without a Brain installation. They are test data, never runtime routes.

real-pi/ holds a snapshot of the real osslab-manager pi-openrouter-worker.sh and its
templates (Brain branch feat/osslab-manager-resume-key). The integration test runs it
with a fake `pi` on PATH and a throwaway HOME, so the session contract between Relay
and the real helper is exercised without a model call.
