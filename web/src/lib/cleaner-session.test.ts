import { describe, expect, it, vi } from "vitest";
import { clearCleanerId, getCleanerId, KEY, setCleanerId } from "./cleaner-session";

describe("cleaner session", () => {
  it("round-trips set, get and clear", () => {
    expect(getCleanerId()).toBeNull();
    setCleanerId("c1");
    expect(getCleanerId()).toBe("c1");
    expect(localStorage.getItem(KEY)).toBe("c1");
    clearCleanerId();
    expect(getCleanerId()).toBeNull();
  });

  it("survives storage that throws", () => {
    const boom = () => {
      throw new Error("blocked");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(boom);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(boom);

    expect(getCleanerId()).toBeNull();
    expect(() => setCleanerId("c1")).not.toThrow();
    expect(() => clearCleanerId()).not.toThrow();
  });
});
