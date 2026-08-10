import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { CalendarCheck, Clock, Users, FileText, List, CalendarDays, Save, DollarSign, Gift, Plus, X, Search, CalendarRange, UserRoundCheck, BadgePlus, Trash2, Upload, FileSpreadsheet, Download, CheckCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../../context/AuthContext";
import { useToast } from "../ToastContext";
import { getEmployeeRoster, saveAttendanceRecords, getAttendanceRecords, getAttendanceHistory, getHolidays, getPayrollLeaveRequests, getEmployees } from "../../../service/payrollService";
import * as XLSX from "xlsx";

function lsKey(orgId) {
  return orgId ? `zoiko_payroll_attendance_${orgId}` : null;
}

function getLocalRecords(orgId) {
  const key = lsKey(orgId);
  if (!key) return {};
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}

function setLocalRecords(map, orgId) {
  const key = lsKey(orgId);
  if (!key) return;
  try { localStorage.setItem(key, JSON.stringify(map)); } catch {}
}

function mergeLocalIntoRecords(records, date, orgId) {
  const local = getLocalRecords(orgId);
  const dayRecords = local[date];
  if (!dayRecords) return records;
  return records.map((r) => {
    const saved = dayRecords.find((d) => String(d.employeeId) === String(r.employeeId));
    if (!saved) return r;
    return { ...r, ...saved };
  });
}

// A stable per-record identity for de-duping/merging. Falls back to name when
// employeeId is missing (e.g. a name-matched upload with no ID column) — using
// employeeId alone in that case would collapse every unmatched employee sharing
// a date into a single key, silently discarding all but the last one.
function recordKey(rec) {
  const id = rec.employeeId;
  const idPart = (id !== null && id !== undefined && id !== "") ? String(id) : `name:${String(rec.name || rec.employee || "unknown").trim().toLowerCase()}`;
  return `${idPart}-${rec.date}`;
}

function to24h(time, period) {
  if (!time) return "";
  const [h, m] = time.split(":").map(Number);
  if (isNaN(h) || isNaN(m)) return time;
  // If hour is already >= 13, it's likely already 24h format — skip AM/PM conversion
  if (h >= 13 || (h === 0 && period !== "AM")) {
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }
  let h24 = h;
  if (period === "PM" && h < 12) h24 = h + 12;
  if (period === "AM" && h === 12) h24 = 0;
  return `${String(h24).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function calculateHours(checkIn, checkOut, breakMinutes, inPeriod, outPeriod) {
  const ci = inPeriod ? to24h(checkIn, inPeriod) : checkIn;
  const co = outPeriod ? to24h(checkOut, outPeriod) : checkOut;
  if (!ci || !co) return "";
  const [inH, inM] = ci.split(":").map(Number);
  const [outH, outM] = co.split(":").map(Number);
  if (isNaN(inH) || isNaN(inM) || isNaN(outH) || isNaN(outM)) return "";
  const inTotal = inH * 60 + inM;
  const outTotal = outH * 60 + outM;
  let diff = outTotal - inTotal;
  if (diff < 0) diff += 1440;
  const mins = Math.max(0, diff - (Number(breakMinutes) || 0));
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return `${hrs}h ${rem}m`;
}

function calculateDecimalHours(checkIn, checkOut, breakMinutes, inPeriod, outPeriod) {
  const ci = inPeriod ? to24h(checkIn, inPeriod) : checkIn;
  const co = outPeriod ? to24h(checkOut, outPeriod) : checkOut;
  if (!ci || !co) return 0;
  const [inH, inM] = ci.split(":").map(Number);
  const [outH, outM] = co.split(":").map(Number);
  if (isNaN(inH) || isNaN(inM) || isNaN(outH) || isNaN(outM)) return 0;
  const inTotal = inH * 60 + inM;
  const outTotal = outH * 60 + outM;
  let diff = outTotal - inTotal;
  if (diff < 0) diff += 1440;
  const mins = Math.max(0, diff - (Number(breakMinutes) || 0));
  return Math.round((mins / 60) * 100) / 100;
}

function formatHours(hours) {
  if (!hours && hours !== 0) return "-";
  const h = Math.floor(Number(hours));
  const m = Math.round((Number(hours) - h) * 60);
  return `${h}h ${m}m`;
}

const tabs = [
  { id: "overview",      label: "Overview",      icon: CalendarCheck },
  { id: "bulk",          label: "Bulk Attendance", icon: BadgePlus },
  { id: "upload",        label: "Upload Sheet",   icon: Upload },
  { id: "records",       label: "Records",        icon: List },
  { id: "summary",       label: "Summary",        icon: FileText },
];

const STATUS_OPTIONS = ["present", "absent", "leave"];

function toLocalDateStr(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

// Excel worksheet names are limited to 31 characters.
function safeSheetName(name) {
  const cleaned = name.replace(/[\\/?*[\]:]/g, "-");
  return cleaned.slice(0, 31);
}

// Single source of truth for how dates are *displayed* to the user (as plain text,
// e.g. next to <input type="date"> fields, which render in the browser's own
// locale format). Keeps text-based date displays consistent with the native
// date picker instead of leaking raw ISO (YYYY-MM-DD) strings into the UI.
function formatDisplayDate(dateStr) {
  if (!dateStr || dateStr === "all") return dateStr;
  const [y, m, d] = dateStr.split("-");
  if (!y || !m || !d) return dateStr;
  return `${d}-${m}-${y}`;
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function formatMonthYear(dateStr) {
  const [y, m] = dateStr.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

// Distinct "Month Year" labels covered by a set of saved-record dates,
// oldest first — used to name exactly which period(s) are protected from a
// reset (e.g. "July 2026" or "July 2026 and August 2026").
function monthYearLabelsForDates(dates) {
  const seen = new Set();
  const labels = [];
  [...dates].sort().forEach((d) => {
    const label = formatMonthYear(d);
    if (!seen.has(label)) { seen.add(label); labels.push(label); }
  });
  if (labels.length <= 1) return labels[0] || "";
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.slice(0, -1).join(", ")}, and ${labels[labels.length - 1]}`;
}

const TIME_RANGES = [
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "4M", days: 120 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "ALL", days: 0 },
];

function getDateRange(days, startDate) {
  const today = new Date();
  const start = startDate ? new Date(startDate + "T00:00:00") : today;
  if (days <= 0) {
    // "ALL" — from the picked start date through today
    return {
      start: toLocalDateStr(start),
      end: toLocalDateStr(today),
    };
  }
  const end = new Date(start);
  end.setDate(end.getDate() + (days - 1));
  return {
    start: toLocalDateStr(start),
    end: toLocalDateStr(end),
  };
}

function countBusinessDays(start, end, excludeWknds, holidaySet) {
  let count = 0;
  const d = new Date(start + "T00:00:00");
  const endD = new Date(end + "T00:00:00");
  while (d <= endD) {
    const day = d.getDay();
    const ds = toLocalDateStr(d);
    if (excludeWknds && (day === 0 || day === 6)) { d.setDate(d.getDate() + 1); continue; }
    if (holidaySet && holidaySet.has(ds)) { d.setDate(d.getDate() + 1); continue; }
    count++;
    d.setDate(d.getDate() + 1);
  }
  return count;
}

export default function AttendancePage() {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const { user } = useAuth();
  const orgId = user?.organization_id;
  const [activeTab, setActiveTab] = useState("overview");
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [date, setDate] = useState(toLocalDateStr(new Date()));
  const [timeRange, setTimeRange] = useState(30);
  const [historyRecords, setHistoryRecords] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [filterStartDate, setFilterStartDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 29); // default 1M range, ending today
    return toLocalDateStr(d);
  });

  const [bulkMode, setBulkMode] = useState("single");
  const [bulkEmployeeId, setBulkEmployeeId] = useState("");
  const [bulkStartDate, setBulkStartDate] = useState("");
  const [bulkEndDate, setBulkEndDate] = useState("");
  const [bulkClockIn, setBulkClockIn] = useState("");
  const [bulkClockOut, setBulkClockOut] = useState("");
  const [bulkClockInPeriod, setBulkClockInPeriod] = useState("AM");
  const [bulkClockOutPeriod, setBulkClockOutPeriod] = useState("PM");
  const [bulkBreak, setBulkBreak] = useState("");
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const [bulkPreview, setBulkPreview] = useState([]);
  const [excludeWeekends, setExcludeWeekends] = useState(true);
  const [excludeHolidays, setExcludeHolidays] = useState(true);

  const uploadFileInputRef = useRef(null);
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadParsedRows, setUploadParsedRows] = useState([]);
  const [uploadParseError, setUploadParseError] = useState("");
  const [uploadSaving, setUploadSaving] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [pendingOverrideRows, setPendingOverrideRows] = useState(null);
  const [checkingExistingAttendance, setCheckingExistingAttendance] = useState(false);
  const [uploadMode, setUploadMode] = useState("day");
  const [uploadMonth, setUploadMonth] = useState(new Date().getMonth());
  const [uploadYear, setUploadYear] = useState(new Date().getFullYear());
  const [standardHoursPerDay, setStandardHoursPerDay] = useState("8");
  const [holidays, setHolidays] = useState([]);
  const [holidaysLoading, setHolidaysLoading] = useState(false);
  const [showClockChoice, setShowClockChoice] = useState(false);
  // True company-wide headcount (every status), distinct from `records`
  // (Active-only roster) and rangeEmployees (only employees with a saved
  // attendance row in the selected range) — both of those undercount
  // "Total Employees" whenever inactive employees exist or a range simply
  // has no attendance saved for everyone yet.
  const [totalEmployeeCount, setTotalEmployeeCount] = useState(0);

  const loadRecords = useCallback(async () => {
    const requestId = ++recordsRequestIdRef.current;
    setLoading(true);
    const local = getLocalRecords(orgId);
    const localToday = local[date] || [];
    let list = localToday.map((r) => ({
      ...r,
      breakMinutes: r.breakMinutes ?? 60,
      checkInPeriod: r.checkInPeriod || "AM",
      checkOutPeriod: r.checkOutPeriod || "PM",
    }));
    if (requestId === recordsRequestIdRef.current) setRecords(list.length ? list : []);
    try {
      const [rosterData, savedRecords, leaveReqs] = await Promise.all([
        getEmployeeRoster({ status: "Active" }),
        getAttendanceRecords({ startDate: date, endDate: date }),
        getPayrollLeaveRequests({ status: "approved" }),
      ]);
      const approvedList = Array.isArray(leaveReqs) ? leaveReqs : [];
      const leaveMap = new Map();
      approvedList.forEach((lr) => {
        if (!lr.startDate || !lr.endDate) return;
        if (date >= lr.startDate && date <= lr.endDate) {
          leaveMap.set(String(lr.employeeId), lr.leaveType || "paid");
        }
      });
      const savedMap = new Map(
        (Array.isArray(savedRecords) ? savedRecords : []).map((r) => [String(r.employeeId), r])
      );
      let apiList = (Array.isArray(rosterData) ? rosterData : []).map((emp) => {
        const saved = savedMap.get(String(emp.employeeId));
        if (saved) {
          return {
            ...emp,
            ...saved,
            breakMinutes: saved.breakMinutes ?? 60,
            checkInPeriod: saved.checkInPeriod || "AM",
            checkOutPeriod: saved.checkOutPeriod || "PM",
          };
        }
        const approvedLeaveType = leaveMap.get(String(emp.employeeId));
        return {
          ...emp,
          breakMinutes: 60,
          checkInPeriod: "AM",
          checkOutPeriod: "PM",
          status: approvedLeaveType ? "leave" : "present",
          leaveType: approvedLeaveType || undefined,
        };
      });
      apiList = mergeLocalIntoRecords(apiList, date, orgId);
      if (requestId === recordsRequestIdRef.current) setRecords(apiList);
    } catch {
      if (requestId === recordsRequestIdRef.current && !list.length) addToast?.("Loaded from local storage.", "info");
    } finally {
      if (requestId === recordsRequestIdRef.current) setLoading(false);
    }
  }, [addToast, date, orgId]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  function todayStr() {
    return toLocalDateStr(new Date());
  }

  function isFutureDate(dateStr) {
    return !!dateStr && dateStr > todayStr();
  }

  const recordsRequestIdRef = useRef(0);
  const historyRequestIdRef = useRef(0);
  const allRecordsCacheRef = useRef({}); // { [orgId]: { data, fetchedAt } }
  const ALL_CACHE_TTL_MS = 60_000; // reuse the full dataset for up to 60s across filter switches

  const loadHistory = useCallback(async (days) => {
    const requestId = ++historyRequestIdRef.current;
    setHistoryLoading(true);
    const local = getLocalRecords(orgId);
    const range = days === 0 ? null : getDateRange(days, filterStartDate);

    const localSeen = new Map();
    Object.values(local).flat().forEach((rec) => {
      if (!rec?.date) return;
      // Only include records inside the selected date-range filter
      if (range && (rec.date < range.start || rec.date > range.end)) return;
      localSeen.set(recordKey(rec), rec);
    });
    if (requestId === historyRequestIdRef.current) {
      setHistoryRecords([...localSeen.values()]);
    }

    // Reuse a recently-fetched full dataset instead of hitting the network again —
    // this is what makes switching between 1W/1M/4M/6M/1Y/ALL feel instant after the first load.
    const orgCache = allRecordsCacheRef.current[orgId];
    const cacheFresh = orgCache && Date.now() - orgCache.fetchedAt < ALL_CACHE_TTL_MS;
    if (cacheFresh) {
      const scoped = range
        ? orgCache.data.filter((rec) => rec?.date && rec.date >= range.start && rec.date <= range.end)
        : orgCache.data;
      if (requestId === historyRequestIdRef.current) {
        const seen = new Map();
        scoped.forEach((rec) => { seen.set(`${rec.employeeId || rec.employee}-${rec.date}`, rec); });
        setHistoryRecords([...seen.values()]);
        setHistoryLoading(false);
      }
      return;
    }

    try {
      let data;
      if (days === 0) {
        data = await getAttendanceRecords();
        data = Array.isArray(data) ? data : [];
      } else {
        const { start, end } = range;
        data = await getAttendanceHistory(start, end);
        data = Array.isArray(data) ? data : [];
        // Defensive client-side scoping in case the API doesn't bound results itself
        data = data.filter((rec) => rec?.date && rec.date >= start && rec.date <= end);
      }
      // Only "ALL" fetches represent the complete dataset, so only that response is cache-worthy
      if (days === 0) {
        allRecordsCacheRef.current[orgId] = { data, fetchedAt: Date.now() };
      }
      if (data.length && requestId === historyRequestIdRef.current) {
        const seen = new Map();
        data.forEach((rec) => { seen.set(`${rec.employeeId || rec.employee}-${rec.date}`, rec); });
        setHistoryRecords([...seen.values()]);
      }
    } catch {
      // already showing local data
    } finally {
      if (requestId === historyRequestIdRef.current) setHistoryLoading(false);
    }
  }, [filterStartDate, orgId]);

  useEffect(() => {
    loadHistory(timeRange);
  }, [timeRange, loadHistory]);

  // Clean up old unscoped localStorage keys from prior sessions
  useEffect(() => {
    if (!orgId) return;
    const prefix = "zoiko_payroll_attendance";
    const currentKey = lsKey(orgId);
    const toRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix) && key !== currentKey) {
        toRemove.push(key);
      }
    }
    toRemove.forEach((key) => { try { localStorage.removeItem(key); } catch {} });
  }, [orgId]);

  const loadHolidays = useCallback(async () => {
    setHolidaysLoading(true);
    try {
      const data = await getHolidays();
      setHolidays(Array.isArray(data) ? data : data?.items || []);
    } catch {
      setHolidays([]);
    } finally {
      setHolidaysLoading(false);
    }
  }, []);

  useEffect(() => { loadHolidays(); }, [loadHolidays]);

  useEffect(() => {
    getEmployees().then((data) => {
      const list = Array.isArray(data) ? data : data?.items || [];
      setTotalEmployeeCount(list.length);
    }).catch(() => {});
  }, []);

  const holidayDates = useMemo(() => {
    const set = new Set();
    holidays.forEach((h) => { if (h.date) set.add(h.date); });
    return set;
  }, [holidays]);

  function isWorkingDay(dateStr) {
    const d = new Date(dateStr + "T00:00:00");
    const day = d.getDay();
    if (excludeWeekends && (day === 0 || day === 6)) return false;
    if (excludeHolidays && holidayDates.has(dateStr)) return false;
    return true;
  }

  const totalBusinessDaysInRange = useMemo(() => {
    if (timeRange === 0) {
      if (historyRecords.length === 0) return 0;
      const dates = historyRecords.map((r) => r.date).filter(Boolean);
      if (dates.length === 0) return 0;
      const sorted = [...dates].sort();
      return countBusinessDays(sorted[0], sorted[sorted.length - 1], excludeWeekends, holidayDates);
    }
    const { start, end } = getDateRange(timeRange, filterStartDate);
    return countBusinessDays(start, end, excludeWeekends, holidayDates);
  }, [timeRange, filterStartDate, historyRecords, excludeWeekends, holidayDates]);

  // Aggregate history records by employee — only days that have actually occurred count
  // toward completed attendance stats; future/scheduled entries are excluded here.
  const employeeAttendanceSummary = useMemo(() => {
    const map = {};
    (Array.isArray(historyRecords) ? historyRecords : [])
      .filter((rec) => !isFutureDate(rec.date))
      .forEach((rec) => {
      const key = rec.employeeId || rec.employee || rec.name || "unknown";
      if (!map[key]) {
        map[key] = {
          employeeId: rec.employeeId,
          name: rec.name || rec.employee || "Unknown",
          department: rec.department || "",
          present: 0,
          absent: 0,
          leave: 0,
          unpaidLeave: 0,
          paidLeave: 0,
          totalHours: 0,
          days: 0,
          checkInCounts: {},
          checkOutCounts: {},
          breakMinutes: 0,
          breakCount: 0,
        };
      }
      if (rec.status === "present") map[key].present++;
      else if (rec.status === "absent") map[key].absent++;
      else if (rec.status === "leave") {
        map[key].leave++;
        // Mirrors the backend's own convention exactly (_count_unpaid_leave_days
        // in service.py): leaveType "unpaid" or missing/legacy (null) counts as
        // unpaid; "paid" does not; sick/casual count toward Leave Days only.
        if (rec.leaveType === "paid") map[key].paidLeave++;
        else if (rec.leaveType == null || rec.leaveType === "unpaid") map[key].unpaidLeave++;
      }
      map[key].days++;
      map[key].totalHours += Number(rec.hours || rec.totalHours || 0);
      const ci = rec.checkIn || "";
      if (ci) map[key].checkInCounts[ci] = (map[key].checkInCounts[ci] || 0) + 1;
      const co = rec.checkOut || "";
      if (co) map[key].checkOutCounts[co] = (map[key].checkOutCounts[co] || 0) + 1;
      const bm = Number(rec.breakMinutes) || 0;
      if (bm > 0) { map[key].breakMinutes += bm; map[key].breakCount++; }
    });

    // If no history records, fall back to today's records for per-employee view
    if (Object.keys(map).length === 0) {
      records.forEach((r) => {
        const key = r.employeeId || r.name || "unknown";
        if (!map[key]) {
          map[key] = {
            employeeId: r.employeeId,
            name: r.name,
            department: r.department || "",
            present: r.status === "present" ? 1 : 0,
            absent: r.status === "absent" ? 1 : 0,
            leave: r.status === "leave" ? 1 : 0,
            unpaidLeave: r.status === "leave" && (r.leaveType == null || r.leaveType === "unpaid") ? 1 : 0,
            paidLeave: r.status === "leave" && r.leaveType === "paid" ? 1 : 0,
            totalHours: Number(r.hours || 0),
            days: 1,
            checkInCounts: r.checkIn ? { [r.checkIn]: 1 } : {},
            checkOutCounts: r.checkOut ? { [r.checkOut]: 1 } : {},
            breakMinutes: Number(r.breakMinutes) || 0,
            breakCount: Number(r.breakMinutes) ? 1 : 0,
          };
        }
      });
    }

    return Object.values(map).map((emp) => {
      const topCheckIn = Object.entries(emp.checkInCounts).sort((a, b) => b[1] - a[1])[0];
      const topCheckOut = Object.entries(emp.checkOutCounts).sort((a, b) => b[1] - a[1])[0];
      return {
        ...emp,
        // Every field below is a direct, read-only derivation of records actually
        // fetched from the backend for this range — nothing here is user-editable,
        // so the table can never silently drift from what was uploaded/saved.
        totalDays: emp.days,                 // "Total Working Days" — count of recorded attendance days
        present: emp.present,                // "Present Days"
        leave: emp.leave,                    // "Leave Days"
        absent: emp.absent,                  // "Absent Days"
        unpaidLeaves: emp.unpaidLeave,        // "Unpaid Leaves" — leaveType "unpaid"/legacy null only, never paid leave
        paidLeaves: emp.paidLeave,
        totalHours: Math.round(emp.totalHours * 100) / 100,
        avgCheckIn: topCheckIn ? topCheckIn[0] : "",
        avgCheckOut: topCheckOut ? topCheckOut[0] : "",
        avgBreak: emp.breakCount > 0 ? Math.round(emp.breakMinutes / emp.breakCount) : 0,
      };
    });
  }, [historyRecords, records, timeRange]);

  const filteredSummary = useMemo(() => {
    if (!employeeSearch.trim()) return employeeAttendanceSummary;
    const q = employeeSearch.toLowerCase();
    return employeeAttendanceSummary.filter(
      (emp) =>
        emp.name?.toLowerCase().includes(q) ||
        emp.department?.toLowerCase().includes(q)
    );
  }, [employeeAttendanceSummary, employeeSearch]);

  function updateRecord(idx, field, value) {
    setRecords((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  }

  // Permanently wipes UNSAVED draft edits (the local-storage cache used
  // before Save is clicked) for the selected range — but first checks
  // whether any of that range is already saved to the backend. If so, the
  // whole reset is refused with a clear explanation instead of silently
  // skipping or partially clearing — saved attendance is never deleted by
  // this button; that would need its own separate, deliberate action.
  async function handleResetAll() {
    const range = timeRange === 0 ? null : getDateRange(timeRange, filterStartDate);

    let existing = [];
    try {
      existing = await getAttendanceRecords(range ? { startDate: range.start, endDate: range.end } : {});
    } catch {
      addToast?.("Could not verify saved records — try again before resetting.", "error");
      return;
    }

    if (Array.isArray(existing) && existing.length > 0) {
      const savedDates = existing.map((r) => r.date).filter(Boolean);
      const periodLabel = monthYearLabelsForDates(savedDates);
      addToast?.(
        `Sorry, ${periodLabel} data is already saved — we can't wipe it out. Only unsaved edits can be reset.`,
        "error"
      );
      return;
    }

    const rangeLabel = timeRange === 0 ? "all unsaved edits" : "unsaved edits for the selected range";
    if (!window.confirm(`Permanently clear ${rangeLabel}? This cannot be undone.`)) return;

    // Scope localStorage clearing: remove only dates within the selected range
    try {
      if (range) {
        const local = getLocalRecords(orgId);
        const filtered = {};
        Object.keys(local).forEach((d) => {
          if (d < range.start || d > range.end) filtered[d] = local[d];
        });
        setLocalRecords(filtered, orgId);
      } else {
        localStorage.removeItem(lsKey(orgId));
      }
    } catch {}

    // Bust the in-memory cache and re-fetch from the backend, so the UI
    // shows exactly what's actually saved (with unsaved edits now gone)
    // instead of blanking state that may still hold real saved data.
    allRecordsCacheRef.current = {};
    loadHistory(timeRange);
    if (!range || (date >= range.start && date <= range.end)) {
      loadRecords();
    }
    addToast?.(`Unsaved edits permanently cleared for ${range ? `${range.start} to ${range.end}` : "all dates"}.`, "success");
  }

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = records.map((r) => ({
        employeeId: r.employeeId,
        name: r.name,
        date: date,
        checkIn: r.checkIn,
        checkOut: r.checkOut,
        checkInPeriod: r.checkInPeriod || "AM",
        checkOutPeriod: r.checkOutPeriod || "PM",
        breakMinutes: Number(r.breakMinutes) || 0,
        hours: String(calculateDecimalHours(r.checkIn, r.checkOut, r.breakMinutes, r.checkInPeriod, r.checkOutPeriod)),
        status: r.status,
        leaveType: r.status === "leave" ? (r.leaveType || null) : null,
        isHalfDay: !!r.isHalfDay,
        rewards: Number(r.rewards) || 0,
        bonus: Number(r.bonus) || 0,
        otherCompensation: Number(r.otherCompensation) || 0,
        notes: r.notes,
      }));
      const local = getLocalRecords(orgId);
      local[date] = payload;
      setLocalRecords(local, orgId);
      const result = await saveAttendanceRecords(payload);
      allRecordsCacheRef.current = {};
      const savedCount = result?.saved ?? payload.length;
      const skippedCount = result?.skipped ?? 0;
      if (skippedCount > 0) {
        addToast?.(`Saved ${savedCount} record(s). ${skippedCount} skipped.`, "warning");
      } else {
        addToast?.("Attendance records saved.", "success");
      }
      await loadHistory(timeRange);
    } catch {
      addToast?.("Failed to save records.", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleBulkGenerate = async () => {
    if (!bulkStartDate || !bulkEndDate || !bulkClockIn || !bulkClockOut) {
      addToast?.("Please fill in start date, end date, clock in, and clock out.", "error");
      return;
    }
    if (bulkStartDate > bulkEndDate) {
      addToast?.("Start date must be before end date.", "error");
      return;
    }
    if (bulkMode === "single" && !bulkEmployeeId) {
      addToast?.("Please select an employee.", "error");
      return;
    }
    setBulkGenerating(true);
    try {
      const ci24 = to24h(bulkClockIn, bulkClockInPeriod);
      const co24 = to24h(bulkClockOut, bulkClockOutPeriod);
      const breakMins = Number(bulkBreak) || 0;
      const hrs = calculateDecimalHours(bulkClockIn, bulkClockOut, bulkBreak, bulkClockInPeriod, bulkClockOutPeriod);

      // Determine which employees to generate for
      let targetEmployees = [];
      if (bulkMode === "single") {
        const emp = records.find((r) => r.employeeId === Number(bulkEmployeeId));
        if (emp) targetEmployees.push(emp);
      } else {
        targetEmployees = records;
      }

      // `records` only contains Active employees (see loadRecords' getEmployeeRoster
      // call) — an employee set to Inactive/On Leave won't be found here even
      // though they were selected in the dropdown. Surface that distinctly from
      // "no working days in range" below, which is a date-range problem, not an
      // employee problem.
      if (targetEmployees.length === 0) {
        addToast?.(
          bulkMode === "single"
            ? "Selected employee is not Active — attendance can only be recorded for Active employees. Check their status on the Employees page."
            : "No Active employees found to generate attendance for.",
          "error"
        );
        setBulkGenerating(false);
        return;
      }

      // Generate records for each working day
      const toSave = [];
      const start = new Date(bulkStartDate + "T00:00:00");
      const end = new Date(bulkEndDate + "T00:00:00");
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const dateStr = toLocalDateStr(d);
        if (!isWorkingDay(dateStr)) continue;
        targetEmployees.forEach((emp) => {
          toSave.push({
            employeeId: emp.employeeId,
            name: emp.name,
            date: dateStr,
            checkIn: ci24,
            checkOut: co24,
            checkInPeriod: bulkClockInPeriod,
            checkOutPeriod: bulkClockOutPeriod,
            breakMinutes: breakMins,
            hours: String(hrs),
            status: "present",
            rewards: 0,
            bonus: 0,
            otherCompensation: 0,
            notes: "",
          });
        });
      }

      if (toSave.length === 0) {
        addToast?.("No working days found in the selected range.", "info");
        setBulkGenerating(false);
        return;
      }

      // Clear the date range from localStorage first, then insert new records
      const local = getLocalRecords(orgId);
      const dateSet = new Set(toSave.map((r) => r.date));
      dateSet.forEach((d) => { delete local[d]; });
      toSave.forEach((rec) => {
        if (!local[rec.date]) local[rec.date] = [];
        local[rec.date].push(rec);
      });
      setLocalRecords(local, orgId);

      // Merge with existing backend records so we don't create duplicates
      try {
        const existingBackend = await getAttendanceHistory(bulkStartDate, bulkEndDate);
        const merged = new Map();
        (Array.isArray(existingBackend) ? existingBackend : []).forEach((rec) => {
          merged.set(recordKey(rec), rec);
        });
        toSave.forEach((rec) => {
          merged.set(recordKey(rec), rec);
        });
        const result = await saveAttendanceRecords([...merged.values()]);
        const savedCount = result?.saved ?? toSave.length;
        const skippedCount = result?.skipped ?? 0;
        if (skippedCount > 0) {
          addToast?.(`Created ${savedCount} attendance record(s). ${skippedCount} skipped.`, "warning");
        } else {
          addToast?.(`Created ${savedCount} attendance record(s).`, "success");
        }
      } catch {
        addToast?.("Backend save failed, but data saved locally.", "warning");
      }
      allRecordsCacheRef.current = {};
      setBulkPreview([]);
      await loadRecords();
      await loadHistory(timeRange);
    } catch {
      addToast?.("Failed to generate bulk attendance.", "error");
    } finally {
      setBulkGenerating(false);
    }
  };

  const handleBulkPreview = () => {
    if (!bulkStartDate || !bulkEndDate || !bulkClockIn || !bulkClockOut) {
      addToast?.("Please fill in start date, end date, clock in, and clock out.", "error");
      return;
    }
    if (bulkStartDate > bulkEndDate) {
      addToast?.("Start date must be before end date.", "error");
      return;
    }
    const preview = [];
    const start = new Date(bulkStartDate + "T00:00:00");
    const end = new Date(bulkEndDate + "T00:00:00");
    const ci24 = to24h(bulkClockIn, bulkClockInPeriod);
    const co24 = to24h(bulkClockOut, bulkClockOutPeriod);
    const totalHours = calculateHours(bulkClockIn, bulkClockOut, bulkBreak, bulkClockInPeriod, bulkClockOutPeriod);
    const decimalHours = calculateDecimalHours(bulkClockIn, bulkClockOut, bulkBreak, bulkClockInPeriod, bulkClockOutPeriod);
    let skipped = 0;
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const dateStr = toLocalDateStr(d);
      if (!isWorkingDay(dateStr)) { skipped++; continue; }
      preview.push({ date: dateStr, clockIn: ci24, clockOut: co24, break: bulkBreak || "0", hours: totalHours, decimalHours });
    }
    setBulkPreview(preview);
    if (skipped > 0) {
      addToast?.(`${skipped} non-working day(s) excluded (weekends/holidays).`, "info");
    }
  };

  const ATTENDANCE_HEADER_MAP = {
    "employee": "employeeId",
    "employee id": "employeeId",
    "emp id": "employeeId",
    "emp no": "employeeId",
    "emp #": "employeeId",
    "id": "employeeId",
    "name": "name",
    "employee name": "name",
    "emp name": "name",
    "department": "department",
    "dept": "department",
    "date": "date",
    "date (yyyy-mm-dd)": "date",
    "attendance date": "date",
    "attendance date (yyyy-mm-dd)": "date",
    "date of attendance": "date",
    "check in": "checkIn",
    "checkin": "checkIn",
    "clock in": "checkIn",
    "clockin": "checkIn",
    "in time": "checkIn",
    "intime": "checkIn",
    "check out": "checkOut",
    "checkout": "checkOut",
    "clock out": "checkOut",
    "clockout": "checkOut",
    "out time": "checkOut",
    "outtime": "checkOut",
    "status": "status",
    "attendance": "status",
    "leave type": "leaveType",
    "leave_type": "leaveType",
    "leavetype": "leaveType",
    "leavecategory": "leaveType",
    "leave category": "leaveType",
    "notes": "notes",
    "remarks": "notes",
    "comment": "notes",
    "comments": "notes",
    "rewards": "rewards",
    "reward": "rewards",
    "incentive": "rewards",
    "bonus": "bonus",
    "performance bonus": "bonus",
    "other compensation": "otherCompensation",
    "other_compensation": "otherCompensation",
    "additional compensation": "otherCompensation",
    "extras": "otherCompensation",
    "break": "breakMinutes",
    "break (min)": "breakMinutes",
    "break minutes": "breakMinutes",
    "break min": "breakMinutes",
    "fixed break (min)": "breakMinutes",
    "fixed break": "breakMinutes",
    "lunch break": "breakMinutes",
    "hours": "hours",
    "total hours": "hours",
    "total working hours": "hours",
    "work hours": "hours",
    "worked hours": "hours",
    "duration": "hours",
    "total working days": "totalWorkingDays",
    "present days": "presentDays",
    "leave days": "leaveDays",
    "absent days": "absentDays",
  };

  function normalizeAttHeader(h) {
    return String(h || "").trim().toLowerCase().replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim();
  }

  function normalizeAttTime(val) {
    if (!val && val !== 0) return "";
    const s = String(val).trim();
    if (!s || s === "\u2014" || s === "-" || s === "--") return ""; // em-dash / blank punch placeholder
    if (/^\d{1,2}:\d{2}$/.test(s)) return s;
    // 12-hour with seconds and am/pm, e.g. "09:37:38 am" — not parseable by bare `new Date()`
    // since it has no date component.
    const twelveHourMatch = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]m)$/i);
    if (twelveHourMatch) {
      let h = Number(twelveHourMatch[1]);
      const m = twelveHourMatch[2];
      const period = twelveHourMatch[3].toLowerCase();
      if (period === "pm" && h < 12) h += 12;
      if (period === "am" && h === 12) h = 0;
      return `${String(h).padStart(2, "0")}:${m}`;
    }
    const dateVal = val instanceof Date ? val : new Date(s);
    if (!isNaN(dateVal.getTime())) {
      const h = dateVal.getHours();
      const m = dateVal.getMinutes();
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
    }
    return "";
  }

  function normalizeAttDate(val) {
    if (!val) return "";
    if (val instanceof Date && !isNaN(val)) return toLocalDateStr(val);
    const s = String(val).trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    const d = new Date(s);
    if (!isNaN(d.getTime()) && /\d{4}/.test(s)) return toLocalDateStr(d);
    return s;
  }

  function normalizeAttStatus(val) {
    const s = String(val || "").trim().toLowerCase();
    if (s === "present" || s === "p" || s === "1" || s === "yes" || s === "y" || s === "true") return "present";
    if (s === "absent" || s === "a" || s === "0" || s === "no" || s === "n" || s === "false") return "absent";
    if (s === "leave" || s === "l" || s === "pl" || s === "cl" || s === "sl" || s === "ul" || s === "lop" || s === "half day") return "leave";
    if (s) return "present";
    return "present";
  }

  function normalizeAttLeaveType(val) {
    const s = String(val || "").trim().toLowerCase();
    if (s === "paid" || s === "pl" || s === "paid leave") return "paid";
    if (s === "unpaid" || s === "ul" || s === "unpaid leave" || s === "lop") return "unpaid";
    if (s === "sick" || s === "sl" || s === "sick leave" || s === "medical") return "sick";
    if (s === "casual" || s === "cl" || s === "casual leave") return "casual";
    if (s === "compoff" || s === "comp off" || s === "comp-off" || s === "compensatory") return "compOff";
    return null;
  }

  async function parseAttendanceFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadFileName(file.name);
    setUploadParseError("");
    setUploadParsedRows([]);
    setUploadResult(null);

    const MONTH_MAP = {
      "jan": 0, "january": 0, "feb": 1, "february": 1, "mar": 2, "march": 2,
      "apr": 3, "april": 3, "may": 4, "jun": 5, "june": 5,
      "jul": 6, "july": 6, "aug": 7, "august": 7, "sep": 8, "september": 8,
      "oct": 9, "october": 9, "nov": 10, "november": 10, "dec": 11, "december": 11,
    };

    function detectMonthFromSheetName(name) {
      const lower = String(name).trim().toLowerCase();
      for (const [key, val] of Object.entries(MONTH_MAP)) {
        if (lower.includes(key)) return val;
      }
      return null;
    }

    let payrollEmpList = [];
    try {
      payrollEmpList = await getEmployees();
    } catch { payrollEmpList = []; }
    const employeeLookup = payrollEmpList.map((e) => ({
      id: e.id,
      code: e.employeeCode || "",
      name: (e.name || "").trim().toLowerCase(),
      department: e.department || "",
    }));

    function isMatrixSheet(headers) {
      const dayCount = headers.filter((h) => /^\d{1,2}$/.test(String(h).trim()) && Number(h) >= 1 && Number(h) <= 31).length;
      return dayCount >= 15;
    }

    // Locates the real header row inside a report-style sheet that has title/period
    // rows above it (e.g. "Monthly Attendance Report — July 2026", "Total Employees: ...").
    // Returns { headerRowIdx, colIdx } or null if this sheet isn't that format.
    function findSummaryHeaderRow(sheet) {
      const grid = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "" });
      for (let r = 0; r < Math.min(grid.length, 10); r++) {
        const row = grid[r].map((c) => normalizeAttHeader(c));
        const nameIdx = row.findIndex((c) => c === "employee name" || c === "employee" || c === "name");
        const workingIdx = row.findIndex((c) => c.includes("total working days") || c.includes("working days"));
        const presentIdx = row.findIndex((c) => c.includes("present days") || c === "present");
        if (nameIdx !== -1 && (workingIdx !== -1 || presentIdx !== -1)) {
          const leaveIdx = row.findIndex((c) => c.includes("leave days") || c === "leave");
          const absentIdx = row.findIndex((c) => c.includes("absent days") || c === "absent");
          const idIdx = row.findIndex((c) => c === "employee id" || c === "emp id" || c === "emp no" || c === "id");
          const deptIdx = row.findIndex((c) => c === "department" || c === "dept");
          const checkInIdx = row.findIndex((c) => c.includes("check in") || c.includes("clock in") || c.includes("in time"));
          const checkOutIdx = row.findIndex((c) => c.includes("check out") || c.includes("clock out") || c.includes("out time"));
          const breakIdx = row.findIndex((c) => c.includes("break"));
          const hoursIdx = row.findIndex((c) => c.includes("total hours") || c.includes("total working hours") || c.includes("worked hours") || c === "hours");
          return {
            grid, headerRowIdx: r, nameIdx, workingIdx, presentIdx, leaveIdx, absentIdx,
            idIdx, deptIdx, checkInIdx, checkOutIdx, breakIdx, hoursIdx,
          };
        }
      }
      return null;
    }

    // Parses the aggregate report format (Employee Name / Total Working Days / Present
    // Days / Leave Days / Absent Days). Two template variants are supported:
    //   1. With clock data: includes Check In, Check Out, Break (min)
    //   2. Without clock data: includes Total Hours, Fixed Break (min)
    // Employee ID and Department columns are used when present.
    // Synthesizes per-day records across the month's actual working days.
    function parseSummarySheet(headerInfo, sheetName, monthFromSheet) {
      const { grid, headerRowIdx, nameIdx, workingIdx, presentIdx, leaveIdx, absentIdx,
              idIdx, deptIdx, checkInIdx, checkOutIdx, breakIdx, hoursIdx } = headerInfo;
      const daysInMonth = new Date(uploadYear, monthFromSheet + 1, 0).getDate();
      const workingDates = [];
      for (let day = 1; day <= daysInMonth; day++) {
        const d = new Date(uploadYear, monthFromSheet, day);
        const dow = d.getDay();
        if (dow === 0 || dow === 6) continue;
        if (holidayDates.has(toLocalDateStr(d))) continue;
        workingDates.push(toLocalDateStr(d));
      }

      const hasClockData = checkInIdx !== -1 && checkOutIdx !== -1;
      const hasFixedBreak = breakIdx !== -1 && hoursIdx !== -1;

      const results = [];
      for (let r = headerRowIdx + 1; r < grid.length; r++) {
        const row = grid[r];
        const empName = String(row[nameIdx] || "").trim();
        if (!empName) continue;
        const absentCount = Math.max(0, Number(row[absentIdx]) || 0);
        const leaveCount = Math.max(0, Number(row[leaveIdx]) || 0);
        const presentCount = Math.max(0, Number(row[presentIdx]) || 0);

        const empNameLower = empName.toLowerCase();
        const empNameParts = empNameLower.split(/\s+/).filter(Boolean);
        const empNameReversed = empNameParts.length > 1 ? [...empNameParts].reverse().join(" ") : empNameLower;
        const matched = employeeLookup.find((emp) => {
          if (emp.name === empNameLower) return true;
          if (emp.name === empNameReversed) return true;
          const nameParts = emp.name.split(/\s+/).filter(Boolean);
          if (nameParts.length > 1 && empNameLower.includes(nameParts[0]) && empNameLower.includes(nameParts[nameParts.length - 1])) return true;
          return false;
        }) || records.find((rec) => {
          const recName = String(rec.name || "").trim().toLowerCase();
          if (recName === empNameLower) return true;
          if (recName === empNameReversed) return true;
          const recNameParts = recName.split(/\s+/).filter(Boolean);
          if (recNameParts.length > 1 && empNameLower.includes(recNameParts[0]) && empNameLower.includes(recNameParts[recNameParts.length - 1])) return true;
          return false;
        });
        const empIdFromSheet = idIdx !== -1 ? Number(row[idIdx]) || null : null;
        let empIdCode = null;
        let empIdFromCode = null;
        if (!empIdFromSheet && idIdx !== -1) {
          const rawIdVal = String(row[idIdx] || "").trim();
          if (rawIdVal) {
            const codeMatch = employeeLookup.find((e) => e.code && e.code.toLowerCase() === rawIdVal.toLowerCase());
            if (codeMatch) { empIdFromCode = codeMatch.id; empIdCode = codeMatch.code; }
          }
        }
        const empId = empIdFromSheet || empIdFromCode || (matched ? matched.employeeId || matched.id : null);
        const empIdCodeFinal = empIdCode || (matched ? employeeLookup.find((e) => e.id === (matched.employeeId || matched.id))?.code || null : null);
        const matchedEmpName = matched ? matched.name : "";
        const deptFromSheet = deptIdx !== -1 ? String(row[deptIdx] || "").trim() : "";
        const dept = deptFromSheet || (matched ? matched.department : "");

        let templateCheckIn = "";
        let templateCheckOut = "";
        let templateBreak = 60;
        let templateHours = "";

        if (hasClockData) {
          templateCheckIn = checkInIdx !== -1 ? normalizeAttTime(row[checkInIdx]) : "";
          templateCheckOut = checkOutIdx !== -1 ? normalizeAttTime(row[checkOutIdx]) : "";
          templateBreak = breakIdx !== -1 ? (Number(row[breakIdx]) || 60) : 60;
          if (templateCheckIn && templateCheckOut) {
            let ciPeriod = "AM";
            let coPeriod = "PM";
            const ciH = templateCheckIn.split(":").map(Number)[0];
            const coH = templateCheckOut.split(":").map(Number)[0];
            if (ciH >= 12) ciPeriod = "PM";
            if (coH >= 12) coPeriod = "PM";
            templateHours = String(calculateDecimalHours(templateCheckIn, templateCheckOut, templateBreak, ciPeriod, coPeriod));
          }
        } else if (hasFixedBreak) {
          templateBreak = breakIdx !== -1 ? (Number(row[breakIdx]) || 60) : 60;
          templateHours = hoursIdx !== -1 ? String(Number(row[hoursIdx]) || "") : "";
        }

        let cursor = 0;
        const assign = (count, status) => {
          for (let i = 0; i < count && cursor < workingDates.length; i++, cursor++) {
            const record = {
              employeeId: empId,
              name: empName,
              department: dept,
              date: workingDates[cursor],
              checkIn: templateCheckIn,
              checkOut: templateCheckOut,
              status,
              breakMinutes: templateBreak,
              checkInPeriod: templateCheckIn ? (Number(templateCheckIn.split(":")[0]) >= 12 ? "PM" : "AM") : "AM",
              checkOutPeriod: templateCheckOut ? (Number(templateCheckOut.split(":")[0]) >= 12 ? "PM" : "PM") : "PM",
              hours: templateHours,
              rewards: 0,
              bonus: 0,
              otherCompensation: 0,
              notes: "",
            };
            const errors = [];
            if (!record.name && !record.employeeId) errors.push("Employee name or ID is required");
            if (!record.date) errors.push("Date is required");
            if (empIdFromSheet && empId && matchedEmpName) {
              const idFromSheet = employeeLookup.find((e) => e.id === empId);
              if (idFromSheet && idFromSheet.name !== matchedEmpName) {
                const idName = idFromSheet.name;
                const uploadedWords = matchedEmpName.split(/\s+/);
                const expectedWords = idName.split(/\s+/);
                const nameMismatch = !uploadedWords.some((w) => w.length >= 3 && expectedWords.includes(w));
                if (nameMismatch) errors.push(`ID ${empId} belongs to "${idName}" but name on sheet is "${empName}"`);
              }
            }
            results.push({ record, errors, rowNum: r + 1, matchedExisting: existingEmpIds.has(String(empId)) || (empIdCodeFinal && existingEmpIds.has(empIdCodeFinal)) });
          }
        };
        assign(absentCount, "absent");
        assign(leaveCount, "leave");
        assign(presentCount, "present");
      }
      return results;
    }

    // Declared here (outer scope of parseAttendanceFile) rather than inside reader.onload,
    // so it's in scope for parseMatrixSheet too — parseMatrixSheet is a sibling function
    // defined at this level, and JS closures resolve based on where a function is
    // *defined*, not where it's called from.
    const existingEmpIds = new Set([
      ...records.map((r) => String(r.employeeId)),
      ...employeeLookup.map((e) => String(e.id)),
      ...employeeLookup.filter((e) => e.code).map((e) => e.code),
    ]);

    function parseMatrixSheet(rawRows, sheetName, monthFromSheet) {
      const headers = Object.keys(rawRows[0] || {});
      const nameKey = headers.find((h) => ATTENDANCE_HEADER_MAP[normalizeAttHeader(h)] === "name");
      const idKey = headers.find((h) => ATTENDANCE_HEADER_MAP[normalizeAttHeader(h)] === "employeeId");
      const deptKey = headers.find((h) => ATTENDANCE_HEADER_MAP[normalizeAttHeader(h)] === "department");
      const dayHeaders = headers.filter((h) => /^\d{1,2}$/.test(String(h).trim()) && Number(h) >= 1 && Number(h) <= 31);

      const results = [];
      rawRows.forEach((rawRow, idx) => {
        const empName = String(rawRow[nameKey] || "").trim();
        const rawIdVal = rawRow[idKey];
        let empId = rawIdVal ? Number(rawIdVal) : null;
        let empIdCode = null;
        let matchedEmpName = "";
        if (!empId && rawIdVal && String(rawIdVal).trim()) {
          const rawStr = String(rawIdVal).trim();
          const codeMatch = employeeLookup.find((e) => e.code && e.code.toLowerCase() === rawStr.toLowerCase());
          if (codeMatch) { empId = codeMatch.id; empIdCode = codeMatch.code; matchedEmpName = codeMatch.name; }
        } else if (empId) {
          const idMatch = employeeLookup.find((e) => e.id === empId);
          if (idMatch) { empIdCode = idMatch.code; matchedEmpName = idMatch.name; }
        }
        const dept = deptKey ? String(rawRow[deptKey] || "").trim() : "";
        dayHeaders.forEach((dh) => {
          const dayNum = Number(dh);
          const rawVal = String(rawRow[dh] || "").trim().toLowerCase();
          const isHalfDay = rawVal === "half day";
          const statusVal = normalizeAttStatus(rawRow[dh]);
          if (statusVal === "off" && !rawRow[dh]) return;
          const dateStr = toLocalDateStr(new Date(uploadYear, monthFromSheet, dayNum));
          const record = {
            employeeId: empId,
            name: empName,
            department: dept,
            date: dateStr,
            checkIn: "",
            checkOut: "",
            status: statusVal,
            isHalfDay,
            breakMinutes: 60,
            checkInPeriod: "AM",
            checkOutPeriod: "PM",
            hours: "",
            rewards: 0,
            bonus: 0,
            otherCompensation: 0,
            notes: "",
          };
          const errors = [];
          if (!record.name && !record.employeeId) errors.push("Employee name or ID is required");
          if (!record.date) errors.push("Date is required");
          if (record.employeeId && record.name && matchedEmpName) {
            const uploadedName = record.name.toLowerCase().trim();
            if (!uploadedName.includes(matchedEmpName) && !matchedEmpName.includes(uploadedName)) {
              const uploadedWords = uploadedName.split(/\s+/);
              const expectedWords = matchedEmpName.split(/\s+/);
              const nameMismatch = !uploadedWords.some((w) => w.length >= 3 && expectedWords.includes(w));
              if (nameMismatch) errors.push(`Name mismatch: code ${empIdCode || record.employeeId} belongs to "${matchedEmpName}", not "${record.name}"`);
            }
          }
          results.push({ record, errors, rowNum: idx + 2, matchedExisting: existingEmpIds.has(String(record.employeeId)) || (empIdCode && existingEmpIds.has(empIdCode)) });
        });
      });
      return results;
    }

    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const data = new Uint8Array(evt.target.result);
        const workbook = XLSX.read(data, { type: "array", cellDates: true });
        if (workbook.SheetNames.length === 0) throw new Error("No sheets found in the file.");

        let allParsed = [];

        workbook.SheetNames.forEach((sName) => {
          const sheet = workbook.Sheets[sName];

          const summaryInfo = findSummaryHeaderRow(sheet);
          if (summaryInfo) {
            const monthFromSheet = detectMonthFromSheetName(sName);
            const month = monthFromSheet !== null ? monthFromSheet : uploadMonth;
            allParsed = allParsed.concat(parseSummarySheet(summaryInfo, sName, month));
            return;
          }

          const rawRows = XLSX.utils.sheet_to_json(sheet, { defval: "" });
          if (rawRows.length === 0) return;

          const headers = Object.keys(rawRows[0] || {});
          if (isMatrixSheet(headers)) {
            const monthFromSheet = detectMonthFromSheetName(sName);
            const month = monthFromSheet !== null ? monthFromSheet : uploadMonth;
            allParsed = allParsed.concat(parseMatrixSheet(rawRows, sName, month));
          } else {
            const seenEmpDatePairs = new Set();
            rawRows.forEach((rawRow, idx) => {
              const mapped = {};
              for (const [rawHeader, rawValue] of Object.entries(rawRow)) {
                const key = ATTENDANCE_HEADER_MAP[normalizeAttHeader(rawHeader)];
                if (key) mapped[key] = rawValue;
              }
              const rawEmployeeVal = mapped.employeeId;
              const employeeIdNum = rawEmployeeVal ? Number(rawEmployeeVal) : null;
              let resolvedEmpId = !isNaN(employeeIdNum) && employeeIdNum ? employeeIdNum : null;
              let empCodeVal = null;
              let matchedEmpName = "";
              if (!resolvedEmpId && rawEmployeeVal && String(rawEmployeeVal).trim()) {
                const rawStr = String(rawEmployeeVal).trim();
                const codeMatch = employeeLookup.find((e) => e.code && e.code.toLowerCase() === rawStr.toLowerCase());
                if (codeMatch) {
                  resolvedEmpId = codeMatch.id;
                  empCodeVal = codeMatch.code;
                  matchedEmpName = codeMatch.name;
                }
              } else if (resolvedEmpId) {
                const idMatch = employeeLookup.find((e) => e.id === resolvedEmpId);
                if (idMatch) { empCodeVal = idMatch.code; matchedEmpName = idMatch.name; }
              }
              const rawStatus = String(mapped.status || "").trim().toLowerCase();
              const isHalfDay = rawStatus === "half day";
              const looksLikeName = rawEmployeeVal && !resolvedEmpId && !mapped.name;
              const record = {
                employeeId: looksLikeName ? null : resolvedEmpId,
                employeeCode: empCodeVal || (!isNaN(employeeIdNum) ? null : (resolvedEmpId ? null : String(rawEmployeeVal || "").trim())),
                name: looksLikeName ? String(rawEmployeeVal).trim() : String(mapped.name || "").trim(),
                department: String(mapped.department || "").trim(),
                date: normalizeAttDate(mapped.date),
                checkIn: normalizeAttTime(mapped.checkIn),
                checkOut: normalizeAttTime(mapped.checkOut),
                status: normalizeAttStatus(mapped.status),
                isHalfDay,
                // Prefer an explicit "Leave Type" column, but most sheets encode the
                // sub-type directly in the Status cell instead (e.g. "PL"/"CL"/"SL"/"UL")
                // with no separate column at all — fall back to inferring it from
                // Status so that data isn't silently dropped.
                leaveType: normalizeAttLeaveType(mapped.leaveType) || normalizeAttLeaveType(mapped.status),
                breakMinutes: mapped.breakMinutes !== "" && mapped.breakMinutes != null ? Number(mapped.breakMinutes) || 60 : 60,
                checkInPeriod: "AM",
                checkOutPeriod: "PM",
                hours: mapped.hours !== "" && mapped.hours != null ? String(mapped.hours) : "",
                rewards: Number(mapped.rewards) || 0,
                bonus: Number(mapped.bonus) || 0,
                otherCompensation: Number(mapped.otherCompensation) || 0,
                notes: String(mapped.notes || "").trim(),
              };
              if (record.checkIn) {
                const [h] = record.checkIn.split(":").map(Number);
                record.checkInPeriod = h >= 12 ? "PM" : "AM";
              }
              if (record.checkOut) {
                const [h] = record.checkOut.split(":").map(Number);
                record.checkOutPeriod = h >= 12 ? "PM" : "AM";
              }
              if (record.checkIn && record.checkOut) {
                record.hours = String(calculateDecimalHours(record.checkIn, record.checkOut, record.breakMinutes, record.checkInPeriod, record.checkOutPeriod));
              }
              if (record.status !== "leave") {
                record.leaveType = null;
              }
              const errors = [];
              if (!record.name && !record.employeeId) errors.push("Employee name or ID is required");
              if (!record.date) errors.push("Date is required");
              if (record.employeeId && record.name && matchedEmpName) {
                const uploadedName = record.name.toLowerCase().trim();
                if (matchedEmpName && uploadedName && !uploadedName.includes(matchedEmpName) && !matchedEmpName.includes(uploadedName)) {
                  const uploadedWords = uploadedName.split(/\s+/);
                  const expectedWords = matchedEmpName.split(/\s+/);
                  const nameMismatch = !uploadedWords.some((w) => w.length >= 3 && expectedWords.includes(w));
                  if (nameMismatch) errors.push(`Name mismatch: code ${record.employeeCode || record.employeeId} belongs to "${matchedEmpName}", not "${record.name}"`);
                }
              }
              const empDateKey = `${record.employeeId || record.name}|${record.date}`;
              if (record.employeeId && record.date && seenEmpDatePairs.has(empDateKey)) {
                errors.push("Duplicate entry for this employee on this date");
              }
              if (record.employeeId && record.date) seenEmpDatePairs.add(empDateKey);
              allParsed.push({ record, errors, rowNum: idx + 2, matchedExisting: existingEmpIds.has(String(record.employeeId)) || (record.employeeCode && existingEmpIds.has(record.employeeCode)) });
            });
          }
        });

        if (allParsed.length === 0) {
          setUploadParseError("No data rows found. Make sure the first row has headers and there's at least one data row below it.");
          return;
        }
        setUploadParsedRows(allParsed);
      } catch (err) {
        setUploadParseError(err.message || "Could not read this file. Please ensure it's a valid .xlsx file.");
      }
    };
    reader.onerror = () => setUploadParseError("Failed to read the file. Please try again.");
    reader.readAsArrayBuffer(file);
  }

  function handleUploadDragOver(e) { e.preventDefault(); e.stopPropagation(); }
  function handleUploadDrop(e) {
    e.preventDefault(); e.stopPropagation();
    const file = e.dataTransfer?.files?.[0];
    if (file && uploadFileInputRef.current) {
      const dt = new DataTransfer();
      dt.items.add(file);
      uploadFileInputRef.current.files = dt.files;
      parseAttendanceFile({ target: { files: [file] } });
    }
  }

  async function handleUploadSave() {
    const validRows = uploadParsedRows.filter((r) => r.errors.length === 0).map((r) => r.record);
    if (validRows.length === 0) {
      addToast?.("No valid rows to save.", "error");
      return;
    }

    // Check whether this org already has attendance saved anywhere in the
    // date range this upload covers, before silently overwriting it.
    const dates = validRows.map((r) => r.date).filter(Boolean).sort();
    const startDate = dates[0];
    const endDate = dates[dates.length - 1];
    if (startDate && endDate) {
      setCheckingExistingAttendance(true);
      try {
        const existing = await getAttendanceRecords({ startDate, endDate });
        if (Array.isArray(existing) && existing.length > 0) {
          setPendingOverrideRows(validRows);
          return;
        }
      } finally {
        setCheckingExistingAttendance(false);
      }
    }

    await performUploadSave(validRows);
  }

  async function performUploadSave(validRows) {
    setUploadSaving(true);
    try {
      const local = getLocalRecords(orgId);
      const dateGroups = {};
      validRows.forEach((rec) => {
        const d = rec.date;
        if (!dateGroups[d]) dateGroups[d] = [];
        dateGroups[d].push(rec);
      });
      for (const [d, recs] of Object.entries(dateGroups)) {
        if (!local[d]) local[d] = [];
        const existingIds = new Set(local[d].map((r) => recordKey(r)));
        recs.forEach((rec) => {
          if (existingIds.has(recordKey(rec))) {
            local[d] = local[d].map((r) => recordKey(r) === recordKey(rec) ? { ...r, ...rec } : r);
          } else {
            local[d].push(rec);
            existingIds.add(recordKey(rec));
          }
        });
      }
      setLocalRecords(local, orgId);

      let backendResult = null;
      try {
        const merged = new Map();
        for (const rec of validRows) {
          merged.set(recordKey(rec), rec);
        }
        backendResult = await saveAttendanceRecords([...merged.values()]);
      } catch {
        addToast?.("Backend save failed, but data saved locally.", "warning");
      }

      const savedCount = backendResult?.saved ?? validRows.length;
      const skippedCount = backendResult?.skipped ?? 0;
      const skippedDetails = backendResult?.skippedDetails ?? [];

      if (skippedCount > 0) {
        const reasons = skippedDetails.slice(0, 5).map((s) => {
          const label = s.rowName || s.rowId || "Unknown";
          return `${label}: ${s.reason}`;
        }).join("; ");
        const suffix = skippedCount > 5 ? ` …and ${skippedCount - 5} more` : "";
        addToast?.(
          `Imported ${savedCount} record(s). Skipped ${skippedCount}: ${reasons}${suffix}`,
          savedCount > 0 ? "warning" : "error"
        );
      } else {
        addToast?.(`Imported ${savedCount} attendance record(s) from sheet.`, "success");
      }

      setUploadResult({ savedCount, skippedCount, skippedDetails });

      // Merge the bulk-save API's own returned records directly into state
      // instead of an unconditional refetch — mirrors the pattern already
      // used by EmployeeBulkImportModal/EmployeeListPage. The endpoint
      // already returns everything needed (id, status, hours, etc.) for
      // every saved row, so a second round trip to re-fetch the same data
      // back from the server is pure waste, especially on large sheets.
      const savedRecords = backendResult?.records || [];
      if (savedRecords.length) {
        const savedByKey = new Map(savedRecords.map((r) => [recordKey(r), r]));
        setRecords((prev) => {
          const existingKeys = new Set(prev.map(recordKey));
          const merged = prev.map((r) => {
            const saved = savedByKey.get(recordKey(r));
            return saved
              ? { ...r, ...saved, breakMinutes: r.breakMinutes ?? 60, checkInPeriod: r.checkInPeriod || "AM", checkOutPeriod: r.checkOutPeriod || "PM" }
              : r;
          });
          savedRecords
            .filter((r) => r.date === date && !existingKeys.has(recordKey(r)))
            .forEach((r) => merged.push({ ...r, breakMinutes: 60, checkInPeriod: "AM", checkOutPeriod: "PM" }));
          return merged;
        });

        // Keep the 60s "ALL" cache and the currently displayed history table
        // in sync with what was just saved, reusing loadHistory's own
        // range-scoping logic rather than re-fetching from the network.
        const orgCache = allRecordsCacheRef.current[orgId];
        if (orgCache) {
          const cacheMap = new Map(orgCache.data.map((r) => [recordKey(r), r]));
          savedRecords.forEach((r) => cacheMap.set(recordKey(r), r));
          orgCache.data = [...cacheMap.values()];
          const range = timeRange === 0 ? null : getDateRange(timeRange, filterStartDate);
          const scoped = range
            ? orgCache.data.filter((rec) => rec?.date && rec.date >= range.start && rec.date <= range.end)
            : orgCache.data;
          const seen = new Map();
          scoped.forEach((rec) => { seen.set(`${rec.employeeId || rec.employee}-${rec.date}`, rec); });
          setHistoryRecords([...seen.values()]);
        } else {
          await loadHistory(timeRange);
        }
      } else {
        await loadRecords();
        await loadHistory(timeRange);
      }
    } catch {
      addToast?.("Failed to save uploaded attendance.", "error");
    } finally {
      setUploadSaving(false);
    }
  }

  function handleUploadReset() {
    setUploadFileName("");
    setUploadParsedRows([]);
    setUploadParseError("");
    setUploadResult(null);
    if (uploadFileInputRef.current) uploadFileInputRef.current.value = "";
  }

  async function downloadAttendanceTemplate(hasClockData) {
    if (uploadMode !== "day" && hasClockData === undefined) {
      setShowClockChoice(true);
      return;
    }
    setShowClockChoice(false);

    let templateEmployees = [];
    try {
      const data = await getEmployees();
      const list = data?.items || data || [];
      templateEmployees = list.map((e) => ({
        name: e.name || `Employee ${e.employeeCode || e.id}`,
        id: e.id,
        code: e.employeeCode || "",
        dept: e.department || "",
      }));
    } catch {
      templateEmployees = [];
    }
    if (templateEmployees.length === 0) {
      addToast?.("No employees found. Add employees before downloading the template.", "error");
      return;
    }

    const wb = XLSX.utils.book_new();

    if (uploadMode === "day") {
      const headers = [
        "Employee Name", "Employee ID", "Department", "Date (YYYY-MM-DD)",
        "Check In", "Check Out", "Status", "Leave Type", "Break (min)",
        "Total Hours", "Rewards", "Bonus", "Other Compensation", "Notes",
      ];
      const today = new Date();
      const dateStr = toLocalDateStr(today);
      const rows = templateEmployees.map((emp) => ({
        "Employee Name": emp.name,
        "Employee ID": emp.code,
        "Department": emp.dept,
        "Date (YYYY-MM-DD)": dateStr,
        "Check In": "",
        "Check Out": "",
        "Status": "",
        "Leave Type": "",
        "Break (min)": "",
        "Total Hours": "",
        "Rewards": "",
        "Bonus": "",
        "Other Compensation": "",
        "Notes": "",
      }));
      const ws = XLSX.utils.json_to_sheet(rows, { header: headers });
      ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
      XLSX.utils.book_append_sheet(wb, ws, "Attendance");
      XLSX.writeFile(wb, "attendance_upload_template.xlsx");
      return;
    }

    const monthNames = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const monthNamesFull = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const months = uploadMode === "month" ? [uploadMonth] : [0,1,2,3,4,5,6,7,8,9,10,11];

    months.forEach((month) => {
      const daysInMonth = new Date(uploadYear, month + 1, 0).getDate();
      const periodLabel = `01 ${monthNames[month]} ${uploadYear} \u2013 ${daysInMonth} ${monthNames[month]} ${uploadYear}`;

      if (hasClockData) {
        const headers = [
          "Employee Name", "Employee ID", "Department", "Date",
          "Check In", "Check Out", "Break (min)", "Total Hours",
          "Status", "Leave Type", "Rewards", "Bonus", "Other Compensation", "Notes",
        ];
        const dateList = [];
        for (let day = 1; day <= daysInMonth; day++) {
          dateList.push(toLocalDateStr(new Date(uploadYear, month, day)));
        }
        const rows = [];
        for (const emp of templateEmployees) {
          for (const d of dateList) {
            rows.push({
              "Employee Name": emp.name,
              "Employee ID": emp.code,
              "Department": emp.dept,
              "Date": d,
              "Check In": "",
              "Check Out": "",
              "Break (min)": "",
              "Total Hours": "",
              "Status": "",
              "Leave Type": "",
              "Rewards": "",
              "Bonus": "",
              "Other Compensation": "",
              "Notes": "",
            });
          }
        }
        const ws = XLSX.utils.json_to_sheet(rows, { header: headers });
        ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
        XLSX.utils.book_append_sheet(wb, ws, monthNames[month]);
      } else {
        const headers = ["Employee Name", "Employee ID", "Department", "Total Working Days", "Present Days", "Paid Leave", "Unpaid Leave", "Leave", "Absent", "Total Hours", "Fixed Break (min)"];
        const mergeCols = headers.length - 1;
        const blankRow = (fillIndex0) => {
          const row = new Array(headers.length).fill("");
          if (fillIndex0 !== undefined) row[0] = fillIndex0;
          return row;
        };
        const aoa = [
          blankRow(`Monthly Attendance Report \u2014 ${monthNamesFull[month]} ${uploadYear}`),
          blankRow(`Total Employees: ${templateEmployees.length} | Report Period: ${periodLabel}`),
          blankRow(),
          headers,
          ...templateEmployees.map((emp) => {
            const row = blankRow();
            row[0] = emp.name;
            row[1] = emp.code;
            row[2] = emp.dept;
            return row;
          }),
        ];
        const ws = XLSX.utils.aoa_to_sheet(aoa);
        ws["!merges"] = [
          { s: { r: 0, c: 0 }, e: { r: 0, c: mergeCols } },
          { s: { r: 1, c: 0 }, e: { r: 1, c: mergeCols } },
        ];
        ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 18) }));
        XLSX.utils.book_append_sheet(wb, ws, monthNames[month]);
      }
    });

    const clockTag = hasClockData ? "_with_clock" : "_summary";
    const fileName = uploadMode === "month"
      ? `attendance_template_${monthNames[uploadMonth].toLowerCase()}_${uploadYear}${clockTag}.xlsx`
      : `attendance_template_${uploadYear}${clockTag}.xlsx`;
    XLSX.writeFile(wb, fileName);
  }

  function exportAttendance() {
    const wb = XLSX.utils.book_new();
    const now = new Date();
    const dateStamp = toLocalDateStr(now);

    if (activeTab === "overview") {
      const rows = records.map((r) => ({
        "Employee ID": r.employeeId || "",
        "Employee Name": r.name || "",
        "Department": r.department || "",
        "Date": date,
        "Status": r.status || "",
        "Leave Type": r.leaveType || "",
        "Check In": r.checkIn ? `${r.checkIn} ${r.checkInPeriod || ""}`.trim() : "",
        "Check Out": r.checkOut ? `${r.checkOut} ${r.checkOutPeriod || ""}`.trim() : "",
        "Break (min)": r.breakMinutes || 0,
        "Hours": calculateHours(r.checkIn, r.checkOut, r.breakMinutes, r.checkInPeriod, r.checkOutPeriod) || "",
      }));
      const headers = Object.keys(rows[0] || {});
      const ws = XLSX.utils.json_to_sheet(rows.length ? rows : [{ "Employee ID": "" }], { header: headers });
      ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 16) }));
      XLSX.utils.book_append_sheet(wb, ws, safeSheetName(`Daily ${date}`));
      XLSX.writeFile(wb, `attendance_daily_${date}.xlsx`);
      addToast("success", `Exported daily attendance for ${date}`);
      return;
    }

    if (activeTab === "records") {
      const rangeLabel = timeRange === 0 ? "all" : `${timeRange}d`;
      const { start, end } = timeRange > 0 ? getDateRange(timeRange, filterStartDate) : { start: "all", end: "all" };
      const rows = filteredSummary.map((emp) => ({
        "Employee ID": emp.employeeId || "",
        "Employee Name": emp.name || "",
        "Department": emp.department || "",
        "Period Start": start,
        "Period End": end,
        "Total Working Days": emp.totalDays || 0,
        "Present Days": emp.present,
        "Paid Leave": Number(emp.paidLeaves) || 0,
        "Unpaid Leave": Number(emp.unpaidLeaves) || 0,
        "Leave": emp.leave,
        "Absent": emp.absent,
      }));
      const headers = Object.keys(rows[0] || {});
      const ws = XLSX.utils.json_to_sheet(rows.length ? rows : [{ "Employee ID": "" }], { header: headers });
      ws["!cols"] = headers.map((h) => ({ wch: Math.max(h.length, 16) }));
      XLSX.utils.book_append_sheet(wb, ws, safeSheetName(`Records ${start} to ${end}`));
      XLSX.writeFile(wb, `attendance_records_${rangeLabel}_${dateStamp}.xlsx`);
      addToast("success", `Exported attendance records (${start} → ${end})`);
      return;
    }

    if (activeTab === "summary") {
      const summaryRows = [
        { Metric: "Total Employees", Value: totalEmployeeCount },
        { Metric: "Present Days", Value: rangePresent },
        { Metric: "Absent Days", Value: rangeAbsent },
        { Metric: "Leave Days", Value: rangeOnLeave },
        { Metric: "Total Working Days", Value: totalWorkingDays },
      ];
      const wsSummary = XLSX.utils.json_to_sheet(summaryRows);
      wsSummary["!cols"] = [{ wch: 28 }, { wch: 14 }];
      XLSX.utils.book_append_sheet(wb, wsSummary, "Summary");

      const detailRows = filteredSummary.map((emp) => ({
        "Employee ID": emp.employeeId || "",
        "Employee Name": emp.name || "",
        "Department": emp.department || "",
        "Total Working Days": emp.totalDays || 0,
        "Present Days": emp.present || 0,
        "Absent Days": emp.absent || 0,
        "Leave Days": emp.leave || 0,
        "Total Hours": emp.totalHours || 0,
      }));
      const detailHeaders = Object.keys(detailRows[0] || {});
      const wsDetail = XLSX.utils.json_to_sheet(detailRows.length ? detailRows : [{ "Employee ID": "" }], { header: detailHeaders });
      wsDetail["!cols"] = detailHeaders.map((h) => ({ wch: Math.max(h.length, 16) }));
      XLSX.utils.book_append_sheet(wb, wsDetail, "Detail");
      XLSX.writeFile(wb, `attendance_summary_${dateStamp}.xlsx`);
      addToast("success", "Exported attendance summary");
      return;
    }

    addToast("error", "No data to export for this tab");
  }

  const present = records.filter((r) => r.status === "present").length;
  const absent = records.filter((r) => r.status === "absent").length;
  const onLeave = records.filter((r) => r.status === "leave").length;
  const totalWorkingDays = filteredSummary.reduce((s, e) => s + (e.totalDays || e.present), 0);

  // Range-based summary metrics — derived from historyRecords (via filteredSummary)
  // These reflect the full selected time range, including any uploaded sheets
  const rangePresent = filteredSummary.reduce((s, e) => s + (e.present || 0), 0);
  const rangeAbsent = filteredSummary.reduce((s, e) => s + (e.absent || 0), 0);
  const rangeOnLeave = filteredSummary.reduce((s, e) => s + (e.leave || 0), 0);

  return (
    <div className="bg-[#F8F7F4] dark:bg-[#1A1816] min-h-screen p-6 lg:p-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[12px] bg-[#19C58A] flex items-center justify-center shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
            <CalendarCheck size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-[#1A1816] dark:text-[#F0EDE8]">Attendance & Compensation</h1>
            <p className="text-[13px] font-medium text-[#9E9690]">Track attendance, rewards, and bonuses for payroll</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
            />
            {isFutureDate(date) && (
              <span className="text-[10px] font-bold uppercase tracking-widest text-[#F8A60A] bg-[#F8A60A]/10 rounded-full px-3 py-1">
                Scheduled — upcoming day
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[12px] p-1">
            <button
              type="button"
              onClick={() => setDate(todayStr())}
              className="px-3 py-1.5 rounded-[10px] text-[13px] font-semibold text-[#9E9690] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#1A1816] dark:hover:text-[#F0EDE8] transition-all"
            >Today</button>
            <button
              type="button"
              onClick={() => {
                const d = new Date(); d.setDate(d.getDate() + 1);
                setDate(toLocalDateStr(d));
              }}
              className="px-3 py-1.5 rounded-[10px] text-[13px] font-semibold text-[#9E9690] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#1A1816] dark:hover:text-[#F0EDE8] transition-all"
            >+ Tomorrow</button>
            <button
              type="button"
              onClick={() => {
                const d = new Date(); d.setDate(d.getDate() + 7);
                setDate(toLocalDateStr(d));
              }}
              className="px-3 py-1.5 rounded-[10px] text-[13px] font-semibold text-[#9E9690] hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] hover:text-[#1A1816] dark:hover:text-[#F0EDE8] transition-all"
            >+ Next Week</button>
          </div>
          <button
            onClick={exportAttendance}
            className="flex items-center gap-2 bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[12px] px-4 py-2.5 text-[13px] font-bold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A] hover:shadow-[0_2px_8px_rgba(25,197,138,0.15)] hover:-translate-y-[1px]"
          >
            <Download size={15} />
            Export
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50"
          >
            <Save size={15} />
            {saving ? "Saving..." : "Save Records"}
          </button>
        </div>
      </div>
      <p className="text-[11px] font-medium text-[#9E9690] -mt-3">
        Tip: pick a future date above (or use the shortcuts) to pre-schedule attendance for upcoming days — it saves the same way, and won't count toward "Working Days" until that day actually arrives.
      </p>

      <div className="bg-[#F0EDE8] dark:bg-[#38312D] rounded-[14px] p-1 w-fit flex flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-[12px] text-[13px] font-medium transition-all duration-200 ${
              activeTab === t.id ? "bg-white dark:bg-[#221D1A] text-[#19C58A] shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-[#9E9690] hover:text-[#6B6560] dark:hover:text-[#A69B93]"
            }`}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="space-y-6">
          <div className="bg-[#19C58A]/5 border border-[#19C58A]/15 rounded-[14px] px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93]">
            Only <strong>Active</strong> employees are shown. Inactive employees are excluded from attendance tracking.
          </div>
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] hover:-translate-y-[1px]">
              <div className="p-2.5 rounded-[12px] bg-[#9D7BF2]/10">
                <Users className="w-5 h-5 text-[#9D7BF2]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{totalEmployeeCount}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Total Employees</p>
              </div>
            </div>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] hover:-translate-y-[1px]">
              <div className="p-2.5 rounded-[12px] bg-[#19C58A]/10">
                <CalendarCheck className="w-5 h-5 text-[#19C58A]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{present}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Present</p>
              </div>
            </div>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] hover:-translate-y-[1px]">
              <div className="p-2.5 rounded-[12px] bg-[#FF6E86]/10">
                <Clock className="w-5 h-5 text-[#FF6E86]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{absent}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Absent</p>
              </div>
            </div>
            <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 flex items-center gap-3 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition-all duration-200 hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] hover:-translate-y-[1px]">
              <div className="p-2.5 rounded-[12px] bg-[#35B6F5]/10">
                <CalendarDays className="w-5 h-5 text-[#35B6F5]" />
              </div>
              <div>
                <p className="text-[22px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{onLeave}</p>
                <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">On Leave</p>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-4">
              Attendance for {formatDisplayDate(date)}
            </h3>
            {loading ? (
              <div className="text-center py-8 text-[#9E9690] text-[13px]">Loading employees...</div>
            ) : records.length === 0 ? (
              <div className="text-center py-8">
                <CalendarCheck size={32} className="mx-auto mb-2 opacity-40" />
                No employees found. Add employees in the Employees section first.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employee</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Department</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Status</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Leave Type</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Check In</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Check Out</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Break (min)</th>
                      <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Hours</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
                    {records.map((r, i) => (
                      <tr key={r.employeeId || i} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors">
                        <td className="px-4 py-3 font-medium text-[#1A1816] dark:text-[#F0EDE8]">
                          <div className="flex items-center gap-2.5">
                            <div className="h-8 w-8 rounded-full bg-[#19C58A]/10 flex items-center justify-center text-[11px] font-bold text-[#19C58A]">
                              {(r.name || "?").charAt(0).toUpperCase()}
                            </div>
                            {r.name}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-[#6B6560] dark:text-[#A69B93]">{r.department || "-"}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <select
                              value={r.status}
                              onChange={(e) => updateRecord(i, "status", e.target.value)}
                              className={`rounded-[10px] border px-2.5 py-1 text-[11px] font-bold focus:outline-none transition-all duration-200 ${
                                r.status === "present" ? "bg-[#19C58A]/10 border-[#19C58A]/20 text-[#19C58A]"
                                : r.status === "absent" ? "bg-[#FF6E86]/10 border-[#FF6E86]/20 text-[#FF6E86]"
                                : "bg-[#35B6F5]/10 border-[#35B6F5]/20 text-[#35B6F5]"
                              }`}
                            >
                              {STATUS_OPTIONS.map((s) => (
                                <option key={s} value={s}>{s}</option>
                              ))}
                            </select>
                            {r.isHalfDay && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold border bg-[#F8A60A]/10 border-[#F8A60A]/20 text-[#F8A60A]">
                                Half-Day
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {r.status === "leave" ? (
                            <select
                              value={r.leaveType || "paid"}
                              onChange={(e) => updateRecord(i, "leaveType", e.target.value)}
                              className={`rounded-[10px] border px-2.5 py-1 text-[11px] font-bold focus:outline-none transition-all duration-200 ${
                                r.leaveType === "unpaid" ? "bg-[#9E9690]/10 border-[#E5E0D9] text-[#9E9690]"
                                : r.leaveType === "sick" ? "bg-[#FF6E86]/10 border-[#FF6E86]/20 text-[#FF6E86]"
                                : r.leaveType === "compOff" ? "bg-[#9D7BF2]/10 border-[#9D7BF2]/20 text-[#9D7BF2]"
                                : "bg-[#35B6F5]/10 border-[#35B6F5]/20 text-[#35B6F5]"
                              }`}
                            >
                              <option value="paid">Paid</option>
                              <option value="unpaid">Unpaid</option>
                              <option value="sick">Sick</option>
                              <option value="compOff">Comp-Off</option>
                            </select>
                          ) : (
                            <span className="text-[12px] text-[#9E9690]">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex gap-1">
                            <input
                              type="time"
                              value={r.checkIn}
                              onChange={(e) => updateRecord(i, "checkIn", e.target.value)}
                              className="w-20 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-2 py-1 text-[12px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                            />
                            <select
                              value={r.checkInPeriod}
                              onChange={(e) => updateRecord(i, "checkInPeriod", e.target.value)}
                              className="w-14 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-1 py-1 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A] transition-all duration-200"
                            >
                              <option value="AM">AM</option>
                              <option value="PM">PM</option>
                            </select>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex gap-1">
                            <input
                              type="time"
                              value={r.checkOut}
                              onChange={(e) => updateRecord(i, "checkOut", e.target.value)}
                              className="w-20 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-2 py-1 text-[12px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                            />
                            <select
                              value={r.checkOutPeriod}
                              onChange={(e) => updateRecord(i, "checkOutPeriod", e.target.value)}
                              className="w-14 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-1 py-1 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A] transition-all duration-200"
                            >
                              <option value="AM">AM</option>
                              <option value="PM">PM</option>
                            </select>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <input
                            type="number"
                            min="0"
                            placeholder="0"
                            value={r.breakMinutes}
                            onChange={(e) => updateRecord(i, "breakMinutes", e.target.value)}
                            className="w-16 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-2 py-1 text-[12px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
                            {calculateHours(r.checkIn, r.checkOut, r.breakMinutes, r.checkInPeriod, r.checkOutPeriod) || "-"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "bulk" && (
        <div className="space-y-4">
          <div className="bg-[#F8A60A]/5 border border-[#F8A60A]/15 rounded-[14px] px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93]">
            Please make sure to add attendance details only for <strong>Active Employees</strong>. Inactive employees are excluded from the list.
          </div>
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h3 className="text-base font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-4 flex items-center gap-2">
              <BadgePlus size={18} className="text-[#F8A60A]" />
              Bulk Attendance Generation
            </h3>
            <p className="text-[13px] text-[#9E9690] mb-6">
              Create attendance records for a date range with a single clock-in / clock-out / break template.
            </p>

            {/* Mode selection */}
            <div className="flex gap-4 mb-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="bulkMode" value="single" checked={bulkMode === "single"}
                  onChange={() => setBulkMode("single")} className="accent-[#19C58A]" />
                <span className="text-[13px] font-medium text-[#1A1816] dark:text-[#F0EDE8]">Single Employee</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="bulkMode" value="all" checked={bulkMode === "all"}
                  onChange={() => setBulkMode("all")} className="accent-[#19C58A]" />
                <span className="text-[13px] font-medium text-[#1A1816] dark:text-[#F0EDE8]">All Employees</span>
              </label>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              {bulkMode === "single" && (
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Employee</label>
                  <select value={bulkEmployeeId} onChange={(e) => setBulkEmployeeId(e.target.value)}
                    className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
                  >
                    <option value="">Select employee...</option>
                    {records.map((r) => (
                      <option key={r.employeeId} value={r.employeeId}>{r.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Start Date</label>
                <input type="date" value={bulkStartDate} onChange={(e) => setBulkStartDate(e.target.value)}
                  className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">End Date</label>
                <input type="date" value={bulkEndDate} onChange={(e) => setBulkEndDate(e.target.value)}
                  className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Clock In</label>
                <div className="flex gap-1">
                  <input type="time" value={bulkClockIn} onChange={(e) => setBulkClockIn(e.target.value)}
                    className="flex-1 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
                  <select value={bulkClockInPeriod} onChange={(e) => setBulkClockInPeriod(e.target.value)}
                    className="w-16 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-1 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A] transition-all duration-200"
                  ><option value="AM">AM</option><option value="PM">PM</option></select>
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Clock Out</label>
                <div className="flex gap-1">
                  <input type="time" value={bulkClockOut} onChange={(e) => setBulkClockOut(e.target.value)}
                    className="flex-1 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
                  <select value={bulkClockOutPeriod} onChange={(e) => setBulkClockOutPeriod(e.target.value)}
                    className="w-16 rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-1 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A] transition-all duration-200"
                  ><option value="AM">AM</option><option value="PM">PM</option></select>
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Break (minutes)</label>
                <input type="number" min="0" placeholder="e.g. 60" value={bulkBreak} onChange={(e) => setBulkBreak(e.target.value)}
                  className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">Total Hours / Day</label>
                <div className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F0EDE8] dark:bg-[#2A2520] px-3.5 py-2.5 text-[13px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">
                  {calculateHours(bulkClockIn, bulkClockOut, bulkBreak, bulkClockInPeriod, bulkClockOutPeriod) || "—"}
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-1.5">1 Day = ? Hours</label>
                <input type="number" min="1" step="0.5" placeholder="8" value={standardHoursPerDay} onChange={(e) => setStandardHoursPerDay(e.target.value)}
                  className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3.5 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200" />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-4 mb-4 p-3 bg-[#F8F7F4] dark:bg-[#1A1816] rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D]">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={excludeWeekends} onChange={(e) => setExcludeWeekends(e.target.checked)} className="accent-[#19C58A] rounded" />
                <span className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">Exclude Sat &amp; Sun</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={excludeHolidays} onChange={(e) => setExcludeHolidays(e.target.checked)} className="accent-[#19C58A] rounded" />
                <span className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">Exclude Holidays <span className="text-[11px] text-[#9E9690]">({holidays.length} loaded)</span></span>
              </label>
            </div>

            <div className="flex items-center gap-3 pt-2 border-t border-[#E5E0D9] dark:border-[#38312D]">
              <button onClick={handleBulkPreview}
                className="flex items-center gap-2 border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
              ><CalendarRange size={15} />Preview</button>
              <button onClick={handleBulkGenerate} disabled={bulkGenerating}
                className="flex items-center gap-2 bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50"
              ><BadgePlus size={15} />{bulkGenerating ? "Generating..." : "Generate & Save"}</button>
            </div>

            {/* Preview table */}
            {bulkPreview.length > 0 && (
              <div className="mt-6">
                <h4 className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Preview — {bulkPreview.length} working day(s) to be created</h4>
                <div className="overflow-x-auto max-h-60 overflow-y-auto border border-[#E5E0D9] dark:border-[#38312D] rounded-[12px]">
                  <table className="w-full text-[13px]">
                    <thead className="bg-[#F8F7F4] dark:bg-[#1A1816] sticky top-0">
                      <tr>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Date</th>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Day</th>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">In</th>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Out</th>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Break</th>
                        <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Hours</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
                      {bulkPreview.map((p, i) => (
                        <tr key={i} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors">
                          <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{p.date}</td>
                          <td className="px-3 py-2 text-[12px] text-[#9E9690]">{["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][new Date(p.date+"T00:00:00").getDay()]}</td>
                          <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{p.clockIn}</td>
                          <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{p.clockOut}</td>
                          <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{p.break} min</td>
                          <td className="px-3 py-2 text-[12px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{p.hours}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === "upload" && (
        <div className="space-y-4">
          <div className="bg-[#35B6F5]/5 border border-[#35B6F5]/15 rounded-[14px] px-4 py-3 text-[13px] text-[#6B6560] dark:text-[#A69B93]">
            Please make sure to add attendance details only for <strong>Active Employees</strong>. Inactive employees present in the upload will be skipped by the system.
          </div>
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h3 className="text-base font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2 flex items-center gap-2">
              <Upload size={18} className="text-[#35B6F5]" />
              Upload Attendance Sheet
            </h3>
            <p className="text-[13px] text-[#9E9690] mb-5">
              Upload an Excel (.xlsx) file with attendance data. Columns are auto-mapped by header name — matching records merge with existing data.
            </p>

            <div className="flex items-center gap-3 flex-wrap mb-5">
              <div className="flex gap-1 bg-[#F0EDE8] dark:bg-[#38312D] rounded-[12px] p-1">
                {[{ id: "day", label: "Day" }, { id: "month", label: "Month" }, { id: "year", label: "Year" }].map((m) => (
                  <button
                    key={m.id}
                    onClick={() => { setUploadMode(m.id); handleUploadReset(); }}
                    className={`px-4 py-1.5 rounded-[10px] text-[12px] font-semibold transition-all ${
                      uploadMode === m.id
                        ? "bg-white dark:bg-[#221D1A] text-[#19C58A] shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                        : "text-[#9E9690] hover:text-[#6B6560] dark:hover:text-[#A69B93]"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              {uploadMode === "month" && (
                <div className="flex items-center gap-2">
                  <select
                    value={uploadMonth}
                    onChange={(e) => { setUploadMonth(Number(e.target.value)); handleUploadReset(); }}
                    className="rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-1.5 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A]"
                  >
                    {["January","February","March","April","May","June","July","August","September","October","November","December"].map((name, i) => (
                      <option key={i} value={i}>{name}</option>
                    ))}
                  </select>
                  <select
                    value={uploadYear}
                    onChange={(e) => { setUploadYear(Number(e.target.value)); handleUploadReset(); }}
                    className="rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-1.5 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A]"
                  >
                    {[2024, 2025, 2026, 2027, 2028].map((y) => (
                      <option key={y} value={y}>{y}</option>
                    ))}
                  </select>
                </div>
              )}
              {uploadMode === "year" && (
                <select
                  value={uploadYear}
                  onChange={(e) => { setUploadYear(Number(e.target.value)); handleUploadReset(); }}
                  className="rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-1.5 text-[12px] font-semibold text-[#6B6560] dark:text-[#A69B93] focus:outline-none focus:border-[#19C58A]"
                >
                  {[2024, 2025, 2026, 2027, 2028].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              )}
              <span className="text-[11px] text-[#9E9690]">
                {uploadMode === "day" && "Template for a single day"}
                {uploadMode === "month" && `Template for all days in ${["January","February","March","April","May","June","July","August","September","October","November","December"][uploadMonth]} ${uploadYear}`}
                {uploadMode === "year" && `Template for all days in ${uploadYear}`}
              </span>
            </div>

            {uploadResult ? (
              <div className="space-y-4">
                <div className={`flex items-center gap-3 rounded-[12px] px-4 py-3.5 text-[13px] font-semibold border ${
                  uploadResult.skippedCount > 0
                    ? "bg-[#F8A60A]/10 text-[#F8A60A] border-[#F8A60A]/20"
                    : "bg-[#19C58A]/10 text-[#19C58A] border-[#19C58A]/20"
                }`}>
                  <CheckCircle size={18} className={uploadResult.skippedCount > 0 ? "text-[#F8A60A]" : "text-[#19C58A]"} />
                  <span>
                    Imported {uploadResult.savedCount} attendance record(s).
                    {uploadResult.skippedCount > 0 && (
                      <span className="font-bold"> Skipped {uploadResult.skippedCount} — employee not matched.</span>
                    )}
                  </span>
                </div>
                {uploadResult.skippedDetails?.length > 0 && (
                  <div className="rounded-[12px] bg-[#FF6E86]/5 border border-[#FF6E86]/15 p-3">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-[#FF6E86] mb-2">Skipped Rows</p>
                    <div className="max-h-32 overflow-y-auto space-y-1">
                      {uploadResult.skippedDetails.map((s, i) => (
                        <div key={i} className="flex items-center justify-between text-[12px] text-[#6B6560] dark:text-[#A69B93]">
                          <span className="font-medium">{s.rowName || s.rowId || `Row ${i + 1}`}{s.date ? ` (${s.date})` : ""}</span>
                          <span className="text-[#FF6E86]">{s.reason}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="flex justify-end gap-3">
                  <button onClick={handleUploadReset}
                    className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
                  >Upload another file</button>
                </div>
              </div>
            ) : (
              <>
                <div
                  className="border-2 border-dashed border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-8 text-center transition-all duration-200 hover:border-[#35B6F5] hover:bg-[#35B6F5]/5"
                  onDragOver={handleUploadDragOver}
                  onDrop={handleUploadDrop}
                >
                  <Upload size={36} className="mx-auto mb-3 text-[#35B6F5]" />
                  <p className="text-[13px] text-[#9E9690] mb-4">
                    Drag &amp; drop your attendance sheet here, or browse to upload.
                  </p>
                  <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
                    <input
                      ref={uploadFileInputRef}
                      type="file"
                      accept=".xlsx,.xls,.csv"
                      onChange={parseAttendanceFile}
                      className="block w-full text-[13px] text-[#9E9690] file:mr-3 file:rounded-[12px] file:border-0 file:bg-[#35B6F5] file:px-4 file:py-2 file:text-[13px] file:font-bold file:text-white file:cursor-pointer file:transition-all duration-200 hover:file:bg-[#2DA0E0] sm:w-auto"
                    />
                  </div>
                  {uploadFileName && (
                    <div className="mt-3 inline-flex items-center gap-2 rounded-[10px] bg-[#F8F7F4] dark:bg-[#2A2520] px-3.5 py-2">
                      <FileSpreadsheet size={14} className="text-[#35B6F5]" />
                      <span className="text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">{uploadFileName}</span>
                    </div>
                  )}
                  <div className="mt-4 pt-4 border-t border-[#E5E0D9] dark:border-[#38312D]">
                    <button type="button" onClick={() => downloadAttendanceTemplate()}
                      className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#35B6F5] hover:text-[#2DA0E0] transition-colors duration-200"
                    ><Download size={14} />Download template</button>
                  </div>
                </div>

                {showClockChoice && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
                    <div className="bg-white dark:bg-[#2A2520] rounded-[18px] shadow-xl w-full max-w-md mx-4 p-6">
                      <h3 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Do you have Clock In &amp; Clock Out data?</h3>
                      <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93] mb-5">
                        Choose the template type based on the data you have for
                        {" "}{uploadMode === "month" ? ["January","February","March","April","May","June","July","August","September","October","November","December"][uploadMonth] : ""} {uploadYear}.
                      </p>
                      <div className="flex flex-col gap-3">
                        <button
                          onClick={() => downloadAttendanceTemplate(true)}
                          className="w-full rounded-[12px] border-2 border-[#19C58A] bg-[#19C58A]/5 px-4 py-3 text-left transition-all hover:bg-[#19C58A]/10"
                        >
                          <span className="text-[13px] font-bold text-[#19C58A]">Yes, I have Clock In &amp; Clock Out</span>
                          <p className="text-[12px] text-[#6B6560] dark:text-[#A69B93] mt-1">
                            Template with Check In, Check Out, Break (min), Total Hours, Status, Leave Type, Notes columns
                          </p>
                        </button>
                        <button
                          onClick={() => downloadAttendanceTemplate(false)}
                          className="w-full rounded-[12px] border-2 border-[#35B6F5] bg-[#35B6F5]/5 px-4 py-3 text-left transition-all hover:bg-[#35B6F5]/10"
                        >
                          <span className="text-[13px] font-bold text-[#35B6F5]">No, I only have summary data</span>
                          <p className="text-[12px] text-[#6B6560] dark:text-[#A69B93] mt-1">
                            Template with Total Hours &amp; Fixed Break (min) columns
                          </p>
                        </button>
                        <button
                          onClick={() => setShowClockChoice(false)}
                          className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] px-4 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] hover:border-[#9E9690] transition-all"
                        >Cancel</button>
                      </div>
                    </div>
                  </div>
                )}

                {uploadParseError && (
                  <div className="mt-4 rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
                    {uploadParseError}
                  </div>
                )}

                {uploadParsedRows.length > 0 && (
                  <div className="mt-5">
                    <div className="mb-3 flex items-center justify-between">
                      <p className="text-[13px] text-[#1A1816] dark:text-[#F0EDE8]">
                        <span className="font-bold text-[#19C58A]">{uploadParsedRows.filter((r) => r.errors.length === 0).length} ready to import</span>
                        {uploadParsedRows.filter((r) => r.errors.length > 0).length > 0 && (
                          <span className="ml-2 text-[#FF6E86]">· {uploadParsedRows.filter((r) => r.errors.length > 0).length} with errors</span>
                        )}
                      </p>
                      <button type="button" onClick={() => { handleUploadReset(); if (uploadFileInputRef.current) uploadFileInputRef.current.click(); }}
                        className="text-[13px] font-semibold text-[#35B6F5] hover:text-[#2DA0E0] transition-colors duration-200"
                      >Re-upload</button>
                    </div>

                    <div className="max-h-80 overflow-auto rounded-[14px] border border-[#E5E0D9] dark:border-[#38312D]">
                      <table className="min-w-full text-[13px]">
                        <thead className="bg-[#F8F7F4] dark:bg-[#1A1816] sticky top-0">
                          <tr>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Row</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employee</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Date</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">In</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Out</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Status</th>
                            <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Errors</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
                          {uploadParsedRows.map((item, i) => (
                            <tr key={i} className={item.errors.length > 0 ? "bg-[#FF6E86]/5" : "hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors"}>
                              <td className="px-3 py-2 text-[12px] text-[#9E9690]">{item.rowNum}</td>
                              <td className="px-3 py-2 font-medium text-[#1A1816] dark:text-[#F0EDE8]">
                                <div className="flex flex-col">
                                  <span>{item.record.name || `ID: ${item.record.employeeId || "?"}`}</span>
                                  {item.record.employeeCode && <span className="text-[10px] text-[#9E9690] font-normal">{item.record.employeeCode}</span>}
                                </div>
                                {item.matchedExisting && <span className="ml-1.5 text-[10px] font-bold text-[#19C58A] bg-[#19C58A]/10 rounded-full px-2 py-0.5">matched</span>}
                              </td>
                              <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{item.record.date || "-"}</td>
                              <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{item.record.checkIn || "-"}</td>
                              <td className="px-3 py-2 text-[12px] text-[#6B6560] dark:text-[#A69B93]">{item.record.checkOut || "-"}</td>
                              <td className="px-3 py-2">
                                <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                                  item.record.status === "present" ? "bg-[#19C58A]/10 text-[#19C58A]"
                                  : item.record.status === "absent" ? "bg-[#FF6E86]/10 text-[#FF6E86]"
                                  : "bg-[#35B6F5]/10 text-[#35B6F5]"
                                }`}>{item.record.status}</span>
                                {item.record.isHalfDay && (
                                  <span className="ml-1 inline-flex items-center rounded-full px-1.5 py-0.5 text-[8px] font-bold bg-[#F8A60A]/10 text-[#F8A60A] border border-[#F8A60A]/20">Half</span>
                                )}
                              </td>
                              <td className="px-3 py-2">
                                {item.errors.length > 0 && (
                                  <ul className="space-y-0.5">
                                    {item.errors.map((err, j) => (
                                      <li key={j} className="text-[11px] text-[#FF6E86]">· {err}</li>
                                    ))}
                                  </ul>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                <div className="mt-6 flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-5">
                  <button onClick={handleUploadReset}
                    className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
                  >Cancel</button>
                  <button onClick={handleUploadSave} disabled={uploadParsedRows.filter((r) => r.errors.length === 0).length === 0 || uploadSaving || checkingExistingAttendance}
                    className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] hover:shadow-[0_4px_14px_rgba(25,197,138,0.4)] hover:-translate-y-[1px] disabled:opacity-50 disabled:hover:translate-y-0"
                  >{checkingExistingAttendance ? "Checking…" : uploadSaving ? "Saving..." : `Save ${uploadParsedRows.filter((r) => r.errors.length === 0).length || ""} Record(s)`}</button>
                </div>

                {pendingOverrideRows && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
                    <div className="bg-white dark:bg-[#2A2520] rounded-[18px] shadow-xl w-full max-w-md mx-4 p-6">
                      <h3 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-2">Attendance already exists</h3>
                      <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93] mb-5">
                        Attendance for this payroll period already exists. Do you want to override the existing attendance?
                      </p>
                      <div className="flex justify-end gap-3">
                        <button
                          onClick={() => setPendingOverrideRows(null)}
                          className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => {
                            const rows = pendingOverrideRows;
                            setPendingOverrideRows(null);
                            performUploadSave(rows);
                          }}
                          className="bg-[#FF6E86] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#E55A72] shadow-[0_2px_8px_rgba(255,110,134,0.3)]"
                        >
                          Override
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="rounded-[12px] bg-[#35B6F5]/10 border border-[#35B6F5]/20 p-4">
            <p className="text-[11px] font-bold text-[#35B6F5] mb-1 uppercase tracking-widest">How it works</p>
            <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">
              <strong>Day mode:</strong> One row per employee — fill in Date, Check In, Check Out, Status, Leave Type, and Notes.<br />
              <strong>Month / Year mode:</strong> One row per employee, columns are day numbers (1, 2, 3…). Fill each cell with a status: <strong>present</strong>, <strong>absent</strong>, <strong>leave</strong>, or <strong>off</strong>. Weekends and holidays are pre-filled as <strong>off</strong>.<br />
              <strong>Clock data (monthly):</strong> One row per employee per day — fill in Check In, Check Out, Break, Status, Leave Type, Rewards, Bonus, and Notes. Total Hours is auto-calculated when both Check In and Check Out are filled; you can also enter it manually for rows without clock times.<br />
              All formats are auto-detected on upload. Headers are matched case-insensitively.
            </p>
          </div>
        </div>
      )}

      {activeTab === "records" && (
        <div className="space-y-4">
          {/* Time Range + Search Filter */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Attendance Records</h3>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-2 bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[12px] px-3 py-2 shadow-[0_1px_3px_rgba(0,0,0,0.04)]" title="Start date">
                <CalendarDays size={14} className="text-[#9E9690]" />
                <input type="date" value={filterStartDate} onChange={(e) => setFilterStartDate(e.target.value)}
                  title="Start date — the range extends forward by the selected duration (1W/1M/4M...)"
                  className="text-xs border-none outline-none bg-transparent text-[#6B6560] dark:text-[#A69B93] font-medium w-28" />
              </div>
              {timeRange > 0 && (
                <span className="text-[11px] text-[#9E9690]">
                  {formatDisplayDate(getDateRange(timeRange, filterStartDate).start)} → {formatDisplayDate(getDateRange(timeRange, filterStartDate).end)}
                </span>
              )}
              <div className="flex gap-1 bg-[#F0EDE8] dark:bg-[#38312D] rounded-[12px] p-1">
                {TIME_RANGES.map((r) => (
                  <button
                    key={r.label}
                    onClick={() => setTimeRange(r.days)}
                    className={`px-3 py-1.5 rounded-[10px] text-[12px] font-semibold transition-all ${
                      timeRange === r.days
                        ? "bg-white dark:bg-[#221D1A] text-[#19C58A] shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                        : "text-[#9E9690] hover:text-[#6B6560] dark:hover:text-[#A69B93]"
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <button onClick={handleResetAll}
                title="Clears unsaved edits only — already-saved attendance is never deleted."
                className="flex items-center gap-1.5 border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-3 py-1.5 text-[12px] font-semibold text-[#FF6E86] transition-all duration-200 hover:border-[#FF6E86]">
                <Trash2 size={14} />
                Clear Unsaved
              </button>
            </div>
          </div>

          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            {/* Employee Search */}
            <div className="relative mb-4">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#9E9690]" />
              <input
                type="text"
                placeholder="Search by employee name or department..."
                value={employeeSearch}
                onChange={(e) => setEmployeeSearch(e.target.value)}
                className="w-full rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] pl-9 pr-3 py-2.5 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200"
              />
            </div>

            {historyLoading ? (
              <div className="text-center py-8 text-[#9E9690] text-[13px]">Loading records...</div>
            ) : employeeAttendanceSummary.length === 0 ? (
              <div className="text-center py-8">
                <List size={32} className="mx-auto mb-2 opacity-40" />
                No attendance records found for this period
              </div>
            ) : (
              <>
                <div className="grid grid-cols-4 gap-3 mb-4">
                  <div className="bg-[#F8F7F4] dark:bg-[#1A1816] rounded-[12px] p-3 text-center border border-[#E5E0D9] dark:border-[#38312D]">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Employees</p>
                    <p className="text-[18px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{filteredSummary.length}</p>
                  </div>
                  <div className="bg-[#19C58A]/10 rounded-[12px] p-3 text-center border border-[#19C58A]/20">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-[#19C58A]">Total Working Days</p>
                    <p className="text-[18px] font-bold text-[#19C58A]">{totalWorkingDays}</p>
                  </div>
                  <div className="bg-[#F8A60A]/10 rounded-[12px] p-3 text-center border border-[#F8A60A]/20">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-[#F8A60A]">Present Days</p>
                    <p className="text-[18px] font-bold text-[#F8A60A]">{filteredSummary.reduce((s, e) => s + e.present, 0)}</p>
                  </div>
                  <div className="bg-[#FF6E86]/10 rounded-[12px] p-3 text-center border border-[#FF6E86]/20">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-[#FF6E86]">Absent Days</p>
                    <p className="text-[18px] font-bold text-[#FF6E86]">{filteredSummary.reduce((s, e) => s + e.absent, 0)}</p>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[#E5E0D9] dark:border-[#38312D]">
                        <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Employee</th>
                        <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Department</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Total Working Days</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Present Days</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Paid Leave</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Unpaid Leave</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Leave</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Absent</th>
                        <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-widest text-[#9E9690]">Total Working Hours</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5E0D9] dark:divide-[#38312D]">
                      {filteredSummary.map((emp, i) => (
                        <tr key={emp.employeeId || i} className="hover:bg-[#F8F7F4] dark:hover:bg-[#2A2520] transition-colors">
                          <td className="px-4 py-3 font-medium text-[#1A1816] dark:text-[#F0EDE8]">
                            <div className="flex items-center gap-2.5">
                              <div className="h-8 w-8 rounded-full bg-[#19C58A]/10 flex items-center justify-center text-[11px] font-bold text-[#19C58A]">
                                {(emp.name || "?").charAt(0).toUpperCase()}
                              </div>
                              {emp.name}
                            </div>
                        </td>
                          <td className="px-4 py-3 text-[#6B6560] dark:text-[#A69B93]">{emp.department || "-"}</td>
                          <td className="px-4 py-3 text-center font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{emp.totalDays || 0}</td>
                          <td className="px-4 py-3 text-center">
                            <span className="inline-flex items-center justify-center min-w-[28px] h-7 px-2 rounded-full bg-[#19C58A]/10 text-[#19C58A] text-[11px] font-bold">
                              {emp.present}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span className="inline-flex items-center justify-center min-w-[28px] h-7 px-2 rounded-full bg-[#35B6F5]/10 text-[#35B6F5] text-[11px] font-bold">
                              {emp.paidLeaves || 0}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span className="inline-flex items-center justify-center min-w-[28px] h-7 px-2 rounded-full bg-[#F8A60A]/10 text-[#F8A60A] text-[11px] font-bold">
                              {emp.unpaidLeaves || 0}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span
                              title="Leave days (all types combined) — click to manage in Payroll Leaves"
                              className="inline-flex items-center justify-center min-w-[28px] h-7 px-2 rounded-full bg-[#9D7BF2]/10 text-[#9D7BF2] text-[11px] font-bold cursor-pointer hover:bg-[#9D7BF2]/20 transition-all"
                              onClick={() => navigate("/payroll/leaves")}
                            >
                              {emp.leave}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span className="inline-flex items-center justify-center min-w-[28px] h-7 px-2 rounded-full bg-[#FF6E86]/10 text-[#FF6E86] text-[11px] font-bold">
                              {emp.absent}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-center font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                            {formatHours(emp.totalHours)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[10px] text-[#9E9690] mt-2">All columns reflect saved attendance records for this period. Leave Days link to Payroll Leaves — click to manage there.</p>
              </>
            )}
          </div>
        </div>
      )}

      {activeTab === "summary" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8] mb-4">Attendance Summary</h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">Total Employees</span>
                <span className="text-[18px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{totalEmployeeCount}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#9D7BF2] font-medium">Active Employees</span>
                <span className="text-[18px] font-bold text-[#9D7BF2]">{records.length}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#19C58A] font-medium">Present Days</span>
                <span className="text-[18px] font-bold text-[#19C58A]">{rangePresent}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#FF6E86] font-medium">Absent Days</span>
                <span className="text-[18px] font-bold text-[#FF6E86]">{rangeAbsent}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#35B6F5] font-medium">Leave Days</span>
                <span className="text-[18px] font-bold text-[#35B6F5]">{rangeOnLeave}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-[#E5E0D9] dark:border-[#38312D]">
                <span className="text-[13px] text-[#F8A60A] font-medium">Total Working Days (selected period)</span>
                <span className="text-[18px] font-bold text-[#F8A60A]">{totalWorkingDays}</span>
              </div>
            </div>
          </div>

          <div className="md:col-span-2 rounded-[12px] bg-[#F8A60A]/10 border border-[#F8A60A]/20 p-4">
            <p className="text-[11px] font-bold text-[#F8A60A] mb-1 uppercase tracking-widest">Payroll Impact</p>
            <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93]">
              Attendance status and working hours are used to calculate accurate payroll.
              Absences and leaves affect gross pay. Save records before creating a payroll run to include this data.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}