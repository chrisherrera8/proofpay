/**
 * A promise opened from outside, for holding an MSW handler in flight.
 * Call `release()` in a `finally` so a failed assertion can't leave the handler hanging.
 * `release` is idempotent.
 */
export function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((r) => (release = r));
  return { promise, release };
}
