import { describe, expect, it } from "vitest";
import { tierById } from "./tiers";

describe("tierById", () => {
  it("finds a tier", () => {
    expect(tierById("deep")).toMatchObject({ id: "deep", price: 20 });
  });

  it.each(["nope", null])("returns undefined for %s", (id) => {
    expect(tierById(id)).toBeUndefined();
  });
});
