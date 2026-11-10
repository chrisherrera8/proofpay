// The signed-in cleaner is just an id in localStorage: a convenience filter, not security.
// Storage can throw (private windows, blocked site data), so every access is wrapped.
const KEY = "proofpay.cleanerId";

export function getCleanerId(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setCleanerId(id: string) {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* storage unavailable: the cleaner can sign up again next visit */
  }
}

export function clearCleanerId() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}
