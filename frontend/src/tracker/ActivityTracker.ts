// Activity-based reading timer.
//
// Time is "active" only while ALL of these hold:
//   - the page is visible (not another tab, not minimised),
//   - the window has focus,
//   - the reader has not been manually paused,
//   - there was a user interaction (mouse, key, scroll, touch, page turn)
//     within the last `inactivityMs`.
// Once the inactivity window passes, counting stops at exactly
// lastInteraction + inactivityMs, so idle time is never counted.
//
// The tracker is pure logic with an injectable clock, so it is unit-tested
// without a browser. The React hook wires DOM events into it.

export type PauseReason = "hidden" | "blurred" | "idle" | "manual" | null;

export interface Drained {
  activeMs: number;
  pageMs: Record<string, number>;
}

export class ActivityTracker {
  private visible = true;
  private focused = true;
  private manual = false;
  private lastInteraction: number;
  private lastTick: number;
  private page: number;
  private pendingActive = 0;
  private pendingPages: Record<string, number> = {};
  private totalActive = 0;
  private pageTotals: Record<string, number> = {};

  constructor(
    page: number,
    private inactivityMs: number,
    private now: () => number = () => Date.now(),
  ) {
    const t = this.now();
    this.lastInteraction = t;
    this.lastTick = t;
    this.page = page;
  }

  /** Account for time elapsed since the previous tick. Call before every state change. */
  tick(): void {
    const t = this.now();
    if (t <= this.lastTick) {
      this.lastTick = Math.max(this.lastTick, t);
      return;
    }
    if (this.visible && this.focused && !this.manual) {
      const activeUntil = Math.min(t, this.lastInteraction + this.inactivityMs);
      const ms = activeUntil - this.lastTick;
      if (ms > 0) {
        this.pendingActive += ms;
        this.totalActive += ms;
        const key = String(this.page);
        this.pendingPages[key] = (this.pendingPages[key] ?? 0) + ms;
        this.pageTotals[key] = (this.pageTotals[key] ?? 0) + ms;
      }
    }
    this.lastTick = t;
  }

  interaction(): void {
    // Interactions while hidden/unfocused do not count (e.g. a background mouse move).
    if (!this.visible) return;
    this.tick();
    this.lastInteraction = this.now();
  }

  setVisible(visible: boolean): void {
    this.tick();
    this.visible = visible;
    if (visible) this.lastInteraction = this.now();
  }

  setFocused(focused: boolean): void {
    this.tick();
    this.focused = focused;
    if (focused) this.lastInteraction = this.now();
  }

  setPage(page: number): void {
    this.tick();
    this.page = page;
    this.lastInteraction = this.now(); // turning a page is an interaction
  }

  pause(): void {
    this.tick();
    this.manual = true;
  }

  resume(): void {
    this.tick();
    this.manual = false;
    this.lastInteraction = this.now();
  }

  setInactivityMs(ms: number): void {
    this.tick();
    this.inactivityMs = ms;
  }

  get currentPage(): number {
    return this.page;
  }

  get pauseReason(): PauseReason {
    if (this.manual) return "manual";
    if (!this.visible) return "hidden";
    if (!this.focused) return "blurred";
    if (this.now() - this.lastInteraction >= this.inactivityMs) return "idle";
    return null;
  }

  get isActive(): boolean {
    return this.pauseReason === null;
  }

  /** Milliseconds until the idle timeout triggers (for a "still reading?" hint). */
  get msUntilIdle(): number {
    return Math.max(0, this.lastInteraction + this.inactivityMs - this.now());
  }

  /** Active ms not yet sent to the server. */
  get pendingMs(): number {
    return this.pendingActive;
  }

  pendingForPage(page: number): number {
    return this.pendingPages[String(page)] ?? 0;
  }

  get totalActiveMs(): number {
    return this.totalActive;
  }

  /** Take everything accumulated since the last drain (for a heartbeat). */
  drain(): Drained {
    this.tick();
    const out = { activeMs: Math.round(this.pendingActive), pageMs: this.pendingPages };
    this.pendingActive = 0;
    this.pendingPages = {};
    return out;
  }

  /** Put drained data back (heartbeat failed for a network reason). */
  restore(d: Drained): void {
    this.pendingActive += d.activeMs;
    for (const [k, v] of Object.entries(d.pageMs)) {
      this.pendingPages[k] = (this.pendingPages[k] ?? 0) + v;
    }
  }
}
