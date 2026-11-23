export interface Settings {
  min_pages: number;
  min_minutes: number;
  min_seconds: number;
  timezone: string;
  reset_minute: number;
  reset_time: string;
  inactivity_timeout_seconds: number;
  min_page_seconds: number;
  streak_reset_day: string | null;
}

export interface Me {
  user: { id: number; username: string; display_name: string };
  membership: { role: "admin" | "member"; joined_at: string; group_id: number } | null;
  group: { id: number; name: string; settings: Settings } | null;
  can_create_group: boolean;
  is_host: boolean;
}

export interface DayProgress {
  day: string;
  pages_read: number;
  active_seconds: number;
  required_pages: number;
  required_seconds: number;
  remaining_pages: number;
  remaining_seconds: number;
  completed: boolean;
  completed_at: string | null;
}

export interface Position {
  page: number;
  juz: number;
  sura: number;
  sura_name: string;
  sura_tname: string;
  khatma: number;
  khatmas_completed: number;
  updated_at: string | null;
}

export interface Assignment {
  id: number;
  start_page: number;
  end_page: number;
  note: string;
  label: string;
  start: { page: number; sura_tname: string; sura_name: string; juz: number };
  end: { page: number; sura_tname: string; sura_name: string; juz: number };
  assigned_at: string;
}

export interface MemberRow {
  user_id: number;
  username: string;
  display_name: string;
  role: string;
  is_you: boolean;
  joined_at: string;
  excused_today: boolean;
  status: "done" | "in_progress" | "not_started" | "new";
  today: DayProgress;
  reading_now: boolean;
  streak: { current: number; longest: number };
  position: Position;
}

export interface Dashboard {
  group: { id: number; name: string; member_count: number; max_members: number };
  now: string;
  today: string;
  day_start: string;
  deadline: string;
  settings: Settings;
  streak: { current: number; longest: number; today_status: string };
  completion: { completed: number; required: number; percent: number; all_done: boolean };
  pages_today: number;
  members: MemberRow[];
  assignment: Assignment | null;
}

export interface CalendarDay {
  day: string;
  status: "success" | "failed" | "neutral" | "pending";
  provisional: boolean;
  completed_count: number;
  required_count: number;
  members: { user_id: number; name: string; outcome: string; pages_read: number; active_seconds: number }[];
}

export interface SessionRow {
  id: number;
  status: string;
  end_reason: string | null;
  started_at: string;
  ended_at: string | null;
  last_heartbeat_at: string;
  start_page: number;
  end_page: number;
  start_sura: string;
  end_sura: string;
  pages_read: number;
  active_seconds: number;
  client_info: string | null;
  user_id?: number;
  name?: string;
}

export interface MemberStats {
  user: { id: number; username: string; display_name: string; role: string | null; joined_at: string | null };
  streak: { current: number; longest: number; today_status: string };
  today: DayProgress;
  totals: { pages: number; active_seconds: number; days_completed: number; sessions: number; khatmas_completed: number };
  position: Position;
  khatma: {
    number: number;
    counted_pages: number[];
    counted: number;
    total_pages: number;
    can_start_new: boolean;
    min_pages_for_new: number;
  };
  history: (DayProgress & { outcome: string })[];
  sessions: SessionRow[];
  deadline: string;
}

export interface Verse {
  sura: number;
  aya: number;
  text: string;
  sura_start: boolean;
  basmala: boolean;
  sajda: string | null;
  quarter_start: boolean;
  quarter: number | null;
  juz_start: number | null;
}

export interface SuraInfo {
  index: number;
  name: string;
  tname: string;
  ename: string;
  type: string;
  ayas: number;
  start_page?: number;
}

export interface QuranPage {
  page: number;
  juz: number;
  juz_end: number;
  basmala_text: string;
  hizb_quarter: number;
  sura: number;
  sura_name: string;
  sura_tname: string;
  total_pages: number;
  suras: SuraInfo[];
  verses: Verse[];
}

export interface QuranMeta {
  total_pages: number;
  total_verses: number;
  suras: (SuraInfo & { start_page: number })[];
  juzs: { index: number; start_page: number }[];
  page_index: { page: number; sura: number; juz: number }[];
  attribution: { source: string; url: string; text: string; license: string; notice: string };
}

export interface ReadingState {
  current_page: number;
  khatma: number;
  counted_pages: number[];
  today: DayProgress;
  current_page_dwell: number;
  current_page_counted: boolean;
  tracking: {
    heartbeat_seconds: number;
    inactivity_timeout_seconds: number;
    min_page_seconds: number;
    stale_session_seconds: number;
  };
}
