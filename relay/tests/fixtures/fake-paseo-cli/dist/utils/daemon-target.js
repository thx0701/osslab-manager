// Test double: the local daemon home, as the real CLI selects by default.
export function selectDaemonTarget() {
  return { kind: "instance", home: "/fake-paseo-home" };
}
