# How reading time, pages and streaks are tracked

This is the honest description of what the app measures and where its limits are.
A browser can show that the reader page was open, visible, focused and being used.
It **cannot** prove that anyone actually read or understood the text, so nothing here claims perfect verification.

## Active reading time

The timer in the reader counts time only while **all** of these hold:

| Condition | What pauses the timer |
|---|---|
| The reader tab is visible | switching to another tab, minimising the browser, locking the phone |
| The browser window has focus | clicking into another program |
| You are not idle | no mouse movement, key press, scroll, touch or page turn for the **inactivity timeout** (default 60 s, set by the admin) |
| You did not press **Pause** | manual pause |

When the inactivity timeout passes, counting stops at exactly *last activity + timeout*, so idle time is never counted.
A "Still reading?" prompt appears, and any tap or key press resumes the timer.

**Tip for slow readers:** a Quran page can take more than a minute. Small scrolls or mouse movements keep the timer alive.
The admin can also raise the timeout to 120–180 s.

### Server-side safeguards

The browser sends a *heartbeat* every 15 seconds with the active milliseconds since the last one, split by page.
The server never trusts that number blindly:

* Credit can never exceed the real wall-clock time since the previous heartbeat (+2 s for network jitter).
* Over a whole session, credit can never exceed the session's real duration.
* One heartbeat can credit at most 60 seconds.
* Heartbeats carry an increasing sequence number, so replayed or duplicated requests add nothing.
* **One live session per person.** Opening the reader in a second tab or on a second device ends the first session ("Reading continued elsewhere"), so time is never double-counted.
* A session that goes silent for 90 seconds (laptop asleep, tab frozen) is closed. The next heartbeat silently starts a fresh session.
* All of this is stored on the host in SQLite, not in the browser.

**Limitation:** someone determined could script fake heartbeats from their own account.
The checks above stop them from crediting more than real elapsed time, but they cannot detect a person who leaves the page open and wiggles the mouse.
This is a group built on trust; the tracker removes accidental and casual over-counting.

## Pages

Pages are the 604 pages of the standard Madani mushaf, using the Tanzil page metadata.

A page counts as **read** the first time it has accumulated **N seconds of active reading time**.
N is the admin setting "Seconds on a page before it counts", default 20 s.

* **Each page counts once per khatma.** Going back to a page, flipping back and forth, or reloading adds nothing.
* **Quick flipping adds nothing.** Fifty pages in ten seconds gives no page enough time.
* **Time on a page adds up across visits,** for example 12 s today plus 8 s later.
* **Khatma:** after counting at least 544 of the 604 pages (90%), a member can start a new khatma on their **Me** page. Every page can then count again. History and streaks are kept.

**Which page are you on?**

* **Mushaf mode** shows one page at a time, so it is that page.
* **Flow mode** flows the text continuously like an e-book. The current page is the one being read at the reading line, about 30% down the screen. It changes when the end-of-page marker passes that line.

Time is credited to whatever page is current, so at a page boundary a few seconds can land on the neighbouring page.

**Limitation:** the app cannot tell whether the eyes were on the text. "Read" means "had the required active time on screen".

## The daily task

A member completes the day when **both** of these are true:

1. pages counted today ≥ the minimum pages (default 2), and
2. active reading time today ≥ the minimum time (default 20 minutes).

Extra pages and time are recorded and shown, but one day can only ever count once toward a streak.

## Reading days, the deadline and midnight

* A reading day is a calendar day in the **group's timezone**. It starts at the **daily reset time** (default 00:00).
  With a 04:00 reset, reading at 02:00 on Tuesday still counts for Monday.
* A heartbeat that spans the reset moment is split: the seconds before the reset go to the old day, the rest to the new day.
  Last-minute reading therefore still counts for the day it happened in.
* A day is **finalised** only 2 minutes after it ends, so in-flight heartbeats can still land.
  Before that a day can never be marked as failed. Finalisation writes a permanent record of every member's outcome. Running it twice changes nothing.
* **Server restarts:** finalisation runs at start-up and every minute.
  If the laptop was off for several days, those days are finalised on the next start. Nobody could read while the server was off, so those days count as missed.

## Changing the rules

* A completed day stays completed forever. Every day stores the requirement it was judged by.
* Changing the requirements applies to today (if not yet complete) and to future days.
  Lowering it can complete today immediately; raising it cannot "un-complete" anyone.
* Changing the timezone first finalises every finished day under the old rules.
  If the new timezone would put "today" on a day that is already finalised, reading is credited to the next open day instead of rewriting history.

## Streaks

* **Individual streak:** consecutive reading days on which the member completed the task.
* **Group streak:** consecutive reading days on which **every** required member completed it.
  If even one member misses a day, the group streak resets to 0.
* **Today is never a failure until it is over.** While today is in progress, the streak shows the days up to yesterday.
  It increases as soon as everyone has completed today.
* **New members** are excused on the day they join: if they don't finish that day, it doesn't break the streak. They are required from the next day.
* **Removed members** stop being required from the moment they are removed.
* A day on which nobody was required is **neutral**: it neither breaks nor extends a streak.
* **Manual reset (admin):** the current group streak restarts from the day after the reset. The longest streak and all history are kept.
* Streaks are computed by pure, deterministic functions over the stored daily records, and these are covered by the test suite.
