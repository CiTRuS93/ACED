import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Console, Facts } from "./main";
import { exposure, reference, requestKey, Run } from "./api";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("operator evidence display", () => {
  it("does not equate held or stopped scheduling with exposure zero", () => {
    for (const status of ["held", "stopping", "stopped"])
      expect(exposure({ status, data: {}, redacted: false } as Run)).toBe(
        "See host status",
      );
    expect(
      exposure({
        data: { experiment_zero: true },
        redacted: true,
      } as unknown as Run),
    ).toBe("Restricted");
  });
  it("only links web references", () => {
    expect(reference("https://host.example/evidence/1")).toContain("https:");
    expect(reference("javascript:alert(1)")).toBeUndefined();
    expect(reference("fixture:evidence")).toBeUndefined();
  });
  it("renders untrusted evidence as text", () => {
    render(<Facts value={{ claim: "<script>alert(1)</script>" }} />);
    expect(screen.getByText(/<script>/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
});

it("refreshes the selected run page without retaining previous-page statuses", async () => {
  let held = false;
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const second = String(input).includes("after=5");
      const run = {
        id: second ? "b" : "a",
        project_id: "demo",
        key: second ? "Second goal" : "First goal",
        status: held ? "held" : "active",
        step: "hypothesize",
        cycle: 1,
        revision: 0,
        redacted: false,
        blocker: null,
        data: {},
      };
      return new Response(
        JSON.stringify({
          items: [{ seq: second ? 6 : 5, run }],
          next: second ? null : 5,
        }),
        { status: 200 },
      );
    });
  render(
    <Console
      context={{
        csrf: "test",
        projects: [{ id: "demo", label: "Demo" }],
        demo: false,
        approvals: false,
        metrics: false,
      }}
    />,
  );
  await screen.findByRole("button", { name: "First goal" });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByRole("button", { name: "Second goal" });
  expect(
    screen.queryByRole("button", { name: "First goal" }),
  ).not.toBeInTheDocument();
  held = true;
  fireEvent.click(screen.getByRole("button", { name: /^Refresh$/ }));
  await waitFor(() =>
    expect(
      screen.getByText("held", { selector: ".badge" }),
    ).toBeInTheDocument(),
  );
  expect(fetcher.mock.calls.at(-1)?.[0]).toContain("after=5");
});

it("creates unpredictable request keys without secure-context randomUUID", () => {
  const first = requestKey();
  expect(first).toMatch(/^[a-f0-9]{32}$/);
  expect(requestKey()).not.toBe(first);
});
