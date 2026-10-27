import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { usePoll } from "./usePoll";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("keeps same-resource observations visibly stale after a failed refresh", async () => {
  const load = vi
    .fn()
    .mockResolvedValueOnce({ value: 1 })
    .mockRejectedValue(new Error("offline"));
  const { result } = renderHook(() => usePoll("run-a", load, 60000));
  await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.error).toBe("offline"));
  expect(result.current.data).toEqual({ value: 1 });
});
it("never carries another resource into a failed selection", async () => {
  const { result, rerender } = renderHook(
    ({ id }) =>
      usePoll(
        id,
        () =>
          id === "a"
            ? Promise.resolve("private-a")
            : Promise.reject(new Error("denied")),
        60000,
      ),
    { initialProps: { id: "a" } },
  );
  await waitFor(() => expect(result.current.data).toBe("private-a"));
  rerender({ id: "b" });
  await waitFor(() => expect(result.current.error).toBe("denied"));
  expect(result.current.data).toBeUndefined();
});
it("ignores a late response for an old selection", async () => {
  let resolve: (value: string) => void = () => {};
  const old = new Promise<string>((r) => {
    resolve = r;
  });
  const { result, rerender } = renderHook(
    ({ id }) =>
      usePoll(id, () => (id === "a" ? old : Promise.resolve("b")), 60000),
    { initialProps: { id: "a" } },
  );
  rerender({ id: "b" });
  await waitFor(() => expect(result.current.data).toBe("b"));
  await act(async () => resolve("a"));
  expect(result.current.data).toBe("b");
});
