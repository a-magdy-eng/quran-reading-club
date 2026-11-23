import { describe, expect, it } from "vitest";
import { ActivityTracker } from "./ActivityTracker";

function setup(inactivityMs = 60_000, page = 1) {
  let t = 1_000_000;
  const clock = { now: () => t, advance: (ms: number) => (t += ms) };
  const tracker = new ActivityTracker(page, inactivityMs, clock.now);
  return { tracker, clock };
}

describe("ActivityTracker", () => {
  it("counts time while visible, focused and recently active", () => {
    const { tracker, clock } = setup();
    clock.advance(10_000);
    tracker.interaction();
    clock.advance(10_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(20_000);
    expect(tracker.isActive).toBe(true);
  });

  it("stops exactly at the inactivity timeout", () => {
    const { tracker, clock } = setup(60_000);
    clock.advance(5 * 60_000); // five idle minutes
    tracker.tick();
    expect(tracker.pendingMs).toBe(60_000);
    expect(tracker.pauseReason).toBe("idle");
  });

  it("resumes counting after an interaction ends an idle pause", () => {
    const { tracker, clock } = setup(60_000);
    clock.advance(120_000);
    tracker.interaction(); // user is back
    expect(tracker.isActive).toBe(true);
    clock.advance(30_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(60_000 + 30_000);
  });

  it("never counts time while the tab is hidden", () => {
    const { tracker, clock } = setup();
    clock.advance(10_000);
    tracker.setVisible(false);
    expect(tracker.pauseReason).toBe("hidden");
    clock.advance(10 * 60_000);
    tracker.interaction(); // ignored while hidden
    tracker.tick();
    expect(tracker.pendingMs).toBe(10_000);
    tracker.setVisible(true);
    clock.advance(5_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(15_000);
  });

  it("never counts time while the window is unfocused", () => {
    const { tracker, clock } = setup();
    clock.advance(1_000);
    tracker.setFocused(false);
    clock.advance(30_000);
    tracker.tick();
    expect(tracker.pauseReason).toBe("blurred");
    expect(tracker.pendingMs).toBe(1_000);
    tracker.setFocused(true);
    clock.advance(2_000);
    expect(tracker.drain().activeMs).toBe(3_000);
  });

  it("supports a manual pause", () => {
    const { tracker, clock } = setup();
    tracker.pause();
    clock.advance(20_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(0);
    expect(tracker.pauseReason).toBe("manual");
    tracker.resume();
    clock.advance(1_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(1_000);
  });

  it("attributes time to the page being read", () => {
    const { tracker, clock } = setup(60_000, 10);
    clock.advance(4_000);
    tracker.setPage(11);
    clock.advance(6_000);
    tracker.setPage(10);
    clock.advance(1_000);
    const d = tracker.drain();
    expect(d.activeMs).toBe(11_000);
    expect(d.pageMs).toEqual({ "10": 5_000, "11": 6_000 });
    expect(tracker.drain()).toEqual({ activeMs: 0, pageMs: {} });
  });

  it("restores drained data after a failed heartbeat", () => {
    const { tracker, clock } = setup(60_000, 3);
    clock.advance(7_000);
    const d = tracker.drain();
    tracker.restore(d);
    clock.advance(1_000);
    expect(tracker.drain()).toEqual({ activeMs: 8_000, pageMs: { "3": 8_000 } });
  });

  it("ignores a clock that goes backwards", () => {
    const { tracker, clock } = setup();
    clock.advance(-50_000);
    tracker.tick();
    expect(tracker.pendingMs).toBe(0);
  });
});
