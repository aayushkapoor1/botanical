import React, { useEffect, useRef, useState } from "react";
import "./App.css";

const MESSAGE_INTERVAL_MS = 100;

function getCalendarDays(year: number, month: number) {
  const first = new Date(year, month, 1);
  const last = new Date(year, month + 1, 0);
  const startPad = first.getDay();
  const daysInMonth = last.getDate();
  const cells: { date: number; key: string; isCurrentMonth: boolean }[] = [];
  const prevMonth = month === 0 ? 11 : month - 1;
  const prevYear = month === 0 ? year - 1 : year;
  const prevLast = new Date(prevYear, prevMonth + 1, 0).getDate();
  for (let i = 0; i < startPad; i++) {
    const d = prevLast - startPad + 1 + i;
    const key = `${prevYear}-${String(prevMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ date: d, key, isCurrentMonth: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ date: d, key, isCurrentMonth: true });
  }
  const remaining = 42 - cells.length;
  for (let i = 1; i <= remaining; i++) {
    const nextMonth = month === 11 ? 0 : month + 1;
    const nextYear = month === 11 ? year + 1 : year;
    const key = `${nextYear}-${String(nextMonth + 1).padStart(2, "0")}-${String(i).padStart(2, "0")}`;
    cells.push({ date: i, key, isCurrentMonth: false });
  }
  return cells;
}

const DAYS = [
  { key: "mon", label: "Monday" },
  { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" },
  { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" },
  { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
] as const;

type DayKey = (typeof DAYS)[number]["key"];

const WEEKDAY_KEYS: DayKey[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function getWeeklyTimesForDate(dateKey: string, schedules: Record<DayKey, string[]>): string[] {
  const d = new Date(dateKey + "T12:00:00");
  const dayKey = WEEKDAY_KEYS[d.getDay()];
  return schedules[dayKey] ?? [];
}

function App() {
  const socketRef = useRef<WebSocket | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sendTimerRef = useRef<number | null>(null);
  const [status, setStatus] = useState("Connecting…");
  const [activeTab, setActiveTab] = useState<"dashboard" | "calendar">("dashboard");
  const [schedules, setSchedules] = useState<Record<DayKey, string[]>>(() =>
    DAYS.reduce((acc, { key }) => ({ ...acc, [key]: [] }), {} as Record<DayKey, string[]>)
  );
  const [scheduleStartDates, setScheduleStartDates] = useState<Partial<Record<DayKey, string>>>({});
  const [calendarView, setCalendarView] = useState<"weekly" | "calendar">("weekly");
  const [calendarMonth, setCalendarMonth] = useState(() => new Date());
  const [dateEvents, setDateEvents] = useState<Record<string, string[]>>({});
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [wateredDates, setWateredDates] = useState<Record<string, string>>({});
  const [waterAllState, setWaterAllState] = useState<"idle" | "watering" | "complete">("idle");
  const [debugMode, setDebugMode] = useState(false);
  const [mockCurrentDate, setMockCurrentDate] = useState<string | null>(null);
  const statusClickCountRef = useRef(0);
  const statusClickTimerRef = useRef<number | null>(null);

  const effectiveToday = debugMode && mockCurrentDate
    ? new Date(mockCurrentDate + "T12:00:00")
    : new Date();

  const todayKey = `${effectiveToday.getFullYear()}-${String(effectiveToday.getMonth() + 1).padStart(2, "0")}-${String(effectiveToday.getDate()).padStart(2, "0")}`;
  const todayKeyRef = useRef(todayKey);
  useEffect(() => {
    todayKeyRef.current = todayKey;
  }, [todayKey]);

  /* --- Debug: 5 clicks on status badge ----------------------------------- */
  /* --- Clear selection when it becomes a past date ----------------------- */
  useEffect(() => {
    if (selectedDate && selectedDate < todayKey) {
      setSelectedDate(null);
    }
  }, [todayKey, selectedDate]);

  const handleStatusClick = () => {
    statusClickCountRef.current += 1;
    if (statusClickTimerRef.current) clearTimeout(statusClickTimerRef.current);
    if (statusClickCountRef.current >= 5) {
      setDebugMode((prev) => !prev);
      statusClickCountRef.current = 0;
    } else {
      statusClickTimerRef.current = window.setTimeout(() => {
        statusClickCountRef.current = 0;
      }, 2000);
    }
  };

  /* --- Water-all mock: 10s completion ------------------------------------ */
  useEffect(() => {
    if (waterAllState !== "watering") return;
    const timeout = window.setTimeout(() => {
      const dateKey = todayKeyRef.current;
      const now = new Date();
      const timeStr = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
      setWateredDates((prev) => ({ ...prev, [dateKey]: timeStr }));
      setWaterAllState("complete");
      setTimeout(() => setWaterAllState("idle"), 1500);
    }, 10000);
    return () => clearTimeout(timeout);
  }, [waterAllState]);

  /* --- WebSocket setup --------------------------------------------------- */
  useEffect(() => {
    const socket = new WebSocket("ws://raspberrypi.local:8000");
    socket.binaryType = "arraybuffer";

    socket.onopen = () => setStatus("Connected");
    socket.onerror = () => setStatus("Error – see console");
    socket.onclose = () => setStatus("Disconnected");

    socket.onmessage = async (event) => {
      if (typeof event.data === "string") {
        setStatus(event.data);
        const msg = event.data.toLowerCase();
        if (msg.includes("complete") && !msg.includes("unimplemented")) {
          const dateKey = todayKeyRef.current;
          const now = new Date();
          const timeStr = now.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
          setWateredDates((prev) => ({ ...prev, [dateKey]: timeStr }));
        }
        return;
      }
      try {
        const blob = new Blob([event.data], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob);
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext("2d");
        if (canvas && ctx) ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
      } catch (err) {
        console.error("Frame decode error:", err);
      }
    };

    socketRef.current = socket;
    return () => socket.close();
  }, []);

  /* --- hold-to-repeat helper -------------------------------------------- */
  const startSending = (cmd: string) => {
    const sock = socketRef.current;
    if (!sock || sock.readyState !== WebSocket.OPEN) return;
    sock.send(cmd);
    sendTimerRef.current = window.setInterval(() => sock.send(cmd), MESSAGE_INTERVAL_MS);
  };

  const stopSending = () => {
    if (sendTimerRef.current !== null) {
      clearInterval(sendTimerRef.current);
      sendTimerRef.current = null;
    }
  };

  /* --- keyboard controls (prevent default scroll) ------------------------ */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return;
      switch (e.key) {
        case "ArrowUp":
        case "ArrowDown":
        case "ArrowLeft":
        case "ArrowRight":
          e.preventDefault();
          startSending(e.key.replace("Arrow", "").toUpperCase());
          break;
        default:
          return;
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (
        ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)
      ) {
        e.preventDefault();
        stopSending();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  /* --- UI helper -------------------------------------------------------- */
  const holdProps = (cmd: string) => ({
    onMouseDown: () => startSending(cmd),
    onMouseUp: stopSending,
    onMouseLeave: stopSending,
    onTouchStart: (e: React.TouchEvent) => {
      e.preventDefault();
      startSending(cmd);
    },
    onTouchEnd: stopSending,
  });

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="app-header-content">
          <h1 className="app-logo">Botanical</h1>
          <nav className="app-tabs">
            <button
              className={`tab ${activeTab === "dashboard" ? "tab--active" : ""}`}
              onClick={() => setActiveTab("dashboard")}
            >
              Dashboard
            </button>
            <button
              className={`tab ${activeTab === "calendar" ? "tab--active" : ""}`}
              onClick={() => setActiveTab("calendar")}
            >
              Calendar
            </button>
          </nav>
          <button
            type="button"
            className="status-badge"
            data-status={status.toLowerCase().includes("connect") ? "connected" : "disconnected"}
            onClick={handleStatusClick}
          >
            <span className="status-dot" />
            {status}
          </button>
        </div>
      </header>

      {debugMode && (
        <div className="debug-panel">
          <span className="debug-label">Debug</span>
          <label className="debug-field">
            Mock current date:
            <input
              type="date"
              value={mockCurrentDate ?? ""}
              onChange={(e) => setMockCurrentDate(e.target.value || null)}
            />
          </label>
          <button
            type="button"
            className="debug-btn"
            onClick={() => {
              setMockCurrentDate(null);
              setDebugMode(false);
            }}
          >
            Close debug
          </button>
        </div>
      )}

      <main className="app-main">
        {activeTab === "dashboard" && (
        <>
        {/* Live view card */}
        <section className="card card--live-view">
          <h2 className="card-title">Live View</h2>
          <div className="canvas-wrapper">
            <canvas ref={canvasRef} width={640} height={480} />
          </div>
        </section>

        {/* Controls card */}
        <section className="card card--controls">
          <h2 className="card-title">Gantry Control</h2>
          <div className="controls-grid">
            <div className="gantry-control">
              <div className="controls-diamond">
                <button className="control-btn control-btn--up" {...holdProps("UP")}>Up</button>
                <button className="control-btn control-btn--left" {...holdProps("LEFT")}>Left</button>
                <button className="control-btn control-btn--right" {...holdProps("RIGHT")}>Right</button>
                <button className="control-btn control-btn--down" {...holdProps("DOWN")}>Down</button>
              </div>
              <p className="gantry-hint">Hold to move • Arrow keys work too</p>
            </div>
            <div className="actions-stack">
              <button
                className="action-btn action-btn--calibrate"
                title="Sends the system to the bottom left corner"
                onClick={() => {
                  const sock = socketRef.current;
                  if (sock && sock.readyState === WebSocket.OPEN) sock.send("CALIBRATE");
                }}
              >
                Calibrate
              </button>
              <button className="action-btn action-btn--water" disabled>
                Water
              </button>
              <span className="action-hint">Water (manual control, unimplemented)</span>
              <button
                className={`action-btn action-btn--water-all ${waterAllState !== "idle" ? "action-btn--water-all-active" : ""}`}
                title={waterAllState === "watering" ? "Cancel watering" : "Starts the water-all-plants routine"}
                onClick={() => {
                  if (waterAllState === "watering") {
                    setWaterAllState("idle");
                    return;
                  }
                  if (waterAllState !== "idle") return;
                  setWaterAllState("watering");
                  const sock = socketRef.current;
                  if (sock && sock.readyState === WebSocket.OPEN) sock.send("WATER_ALL");
                }}
              >
                {waterAllState === "idle" && "Water all plants"}
                {waterAllState === "watering" && "Click to cancel"}
                {waterAllState === "complete" && "Done!"}
              </button>
              <span className="action-hint action-hint--unimplemented">Unimplemented</span>
            </div>
          </div>
        </section>

        {/* Stats card - unimplemented */}
        <section className="card card--stats">
          <h2 className="card-title">Plant Stats</h2>
          <div className="stats-grid">
            <div className="stat-item">
              <span className="stat-label">Last watered</span>
              <span className="stat-value stat-value--unimplemented">—</span>
              <span className="unimplemented-badge">Unimplemented</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">MLs watered</span>
              <span className="stat-value stat-value--unimplemented">—</span>
              <span className="unimplemented-badge">Unimplemented</span>
            </div>
          </div>
        </section>

        {/* Watering schedule - reads from calendar */}
        <section className="card card--schedule">
          <h2
            className="card-title card-title--link"
            onClick={() => {
              setActiveTab("calendar");
            }}
          >
            Watering Schedule
          </h2>
          {(() => {
            const formatTime = (t: string) => {
              const [h, m] = t.split(":").map(Number);
              const h12 = h % 12 || 12;
              const ampm = h < 12 ? "AM" : "PM";
              return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
            };
            const todayWeekly = getWeeklyTimesForDate(todayKey, schedules);
            const todaySpecific = dateEvents[todayKey] ?? [];
            const todayTimes = Array.from(new Set([...todayWeekly, ...todaySpecific])).sort();
            const upcoming: { dateKey: string; label: string; times: string[] }[] = [];
            for (let i = 1; i <= 7; i++) {
              const d = new Date(effectiveToday);
              d.setDate(d.getDate() + i);
              const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
              const w = getWeeklyTimesForDate(k, schedules);
              const s = dateEvents[k] ?? [];
              const times = Array.from(new Set([...w, ...s])).sort();
              if (times.length > 0) {
                upcoming.push({
                  dateKey: k,
                  label: new Date(k + "T12:00:00").toLocaleDateString("default", { weekday: "short", month: "short", day: "numeric" }),
                  times,
                });
              }
            }
            return (
              <div className="schedule-summary">
                <div className="schedule-summary-section">
                  <h3 className="schedule-summary-heading">Today</h3>
                  {todayTimes.length > 0 ? (
                    <ul className="schedule-summary-list">
                      {todayTimes.map((t, i) => (
                        <li key={i}>{formatTime(t)}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="schedule-summary-empty">No watering scheduled for today.</p>
                  )}
                </div>
                <div className="schedule-summary-section">
                  <h3 className="schedule-summary-heading">Upcoming</h3>
                  {upcoming.length > 0 ? (
                    <ul className="schedule-summary-list schedule-summary-list--upcoming">
                      {upcoming.slice(0, 5).map(({ dateKey, label, times }) => (
                        <li key={dateKey}>
                          <span className="schedule-date">{label}</span>
                          <span className="schedule-times">{times.map(formatTime).join(", ")}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="schedule-summary-empty">No upcoming watering scheduled.</p>
                  )}
                </div>
              </div>
            );
          })()}
        </section>
        </>
        )}

        {activeTab === "calendar" && (
          <section className="card card--calendar card--full-width">
            <div className="calendar-toolbar">
              <div className="calendar-subtabs">
                <button
                  className={`tab tab--small ${calendarView === "weekly" ? "tab--active" : ""}`}
                  onClick={() => setCalendarView("weekly")}
                >
                  Weekly
                </button>
                <button
                  className={`tab tab--small ${calendarView === "calendar" ? "tab--active" : ""}`}
                  onClick={() => setCalendarView("calendar")}
                >
                  Calendar
                </button>
              </div>
            </div>

            {calendarView === "weekly" && (
              <>
                <h2 className="card-title">Weekly Watering Schedule</h2>
                <p className="calendar-hint">Set the times you want to water on each day. These routines will run automatically.</p>
                <div className="calendar-grid">
              {DAYS.map(({ key, label }) => (
                <div key={key} className="day-card">
                  <h3 className="day-label">{label}</h3>
                  <div className="day-times">
                    {schedules[key].map((time, i) => (
                      <div key={i} className="time-slot">
                        <span className="time-value">{time}</span>
                        <button
                          type="button"
                          className="time-remove"
                          onClick={() => {
                            setSchedules((prev) => {
                              const next = { ...prev, [key]: prev[key].filter((_, j) => j !== i) };
                              if (next[key].length === 0) {
                                setScheduleStartDates((d) => {
                                  const { [key]: _, ...rest } = d;
                                  return rest;
                                });
                              }
                              return next;
                            });
                          }}
                          aria-label={`Remove ${time}`}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    <div className="day-add">
                      <input
                        type="time"
                        className="time-input"
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v) {
                            setSchedules((prev) => ({
                              ...prev,
                              [key]: [...(prev[key].includes(v) ? prev[key] : [...prev[key], v])].sort(),
                            }));
                            setScheduleStartDates((prev) => (prev[key] ? prev : { ...prev, [key]: todayKey }));
                            e.target.value = "";
                          }
                        }}
                        aria-label={`Add watering time for ${label}`}
                      />
                      <span className="add-hint">Add time</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
              </>
            )}

            {calendarView === "calendar" && (
              <>
                <p className="calendar-hint">Click a date to add or edit watering times.</p>
                <div className="calendar-ribbon">
                  <div className="calendar-ribbon-inner">
                    <button
                      type="button"
                      className="calendar-ribbon-btn"
                      onClick={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() - 1))}
                      aria-label="Previous month"
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M15 18l-6-6 6-6" />
                      </svg>
                    </button>
                    <h2 className="calendar-ribbon-title">
                      {calendarMonth.toLocaleString("default", { month: "long", year: "numeric" })}
                    </h2>
                    <button
                      type="button"
                      className="calendar-ribbon-btn"
                      onClick={() => setCalendarMonth((d) => new Date(d.getFullYear(), d.getMonth() + 1))}
                      aria-label="Next month"
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </button>
                  </div>
                  <button
                    type="button"
                    className="calendar-ribbon-today"
                    onClick={() => setCalendarMonth(effectiveToday)}
                  >
                    Today
                  </button>
                </div>
                <div className="month-grid">
                  {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
                    <div key={i} className="month-grid-header">{d}</div>
                  ))}
                  {getCalendarDays(calendarMonth.getFullYear(), calendarMonth.getMonth()).map(({ date, key, isCurrentMonth }) => {
                    const dayKey = WEEKDAY_KEYS[new Date(key + "T12:00:00").getDay()];
                    const startDate = scheduleStartDates[dayKey];
                    const weeklyTimes = (startDate && key < startDate) ? [] : getWeeklyTimesForDate(key, schedules);
                    const dateSpecific = dateEvents[key] ?? [];
                    const allTimes = Array.from(new Set([...weeklyTimes, ...dateSpecific])).sort();
                    const isSelected = selectedDate === key;
                    const isToday = isCurrentMonth &&
                      effectiveToday.getDate() === date &&
                      effectiveToday.getMonth() === calendarMonth.getMonth() &&
                      effectiveToday.getFullYear() === calendarMonth.getFullYear();
                    const formatTime = (t: string) => {
                      const [h, m] = t.split(":").map(Number);
                      const h12 = h % 12 || 12;
                      const ampm = h < 12 ? "AM" : "PM";
                      return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
                    };
                    const wateredTime = wateredDates[key];
                    const isPast = key < todayKey;
                    const showAsWatered = wateredTime || (isPast && allTimes.length > 0);
                    const displayTime = wateredTime ?? (isPast && allTimes.length > 0 ? formatTime(allTimes[0]) : undefined);
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`month-day ${!isCurrentMonth ? "month-day--other" : ""} ${isSelected ? "month-day--selected" : ""} ${isToday ? "month-day--today" : ""} ${showAsWatered ? "month-day--watered" : ""} ${isPast ? "month-day--past" : ""}`}
                        onClick={() => {
                          if (isPast) return;
                          setSelectedDate((prev) => (prev === key ? null : key));
                        }}
                        disabled={isPast}
                      >
                        <span className="month-day-num-wrapper">
                          <span className="month-day-num">{date}</span>
                        </span>
                        <div className="month-day-banners">
                          {allTimes.slice(0, 3).map((time, i) => (
                            <span key={i} className="month-day-banner" title={formatTime(time)}>
                              {formatTime(time)}
                            </span>
                          ))}
                          {allTimes.length > 3 && (
                            <span className="month-day-more">+{allTimes.length - 3}</span>
                          )}
                          {showAsWatered && displayTime && (
                            <span className="month-day-watered" title={wateredTime ? `Watered at ${wateredTime}` : "Past (before today)"}>
                              {displayTime}
                            </span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
                {selectedDate && (
                  <div
                    className="modal-overlay"
                    onClick={() => setSelectedDate(null)}
                  >
                    <div
                      className="modal"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="modal-header">
                        <h3 className="date-editor-title">
                          {new Date(selectedDate + "T12:00:00").toLocaleDateString("default", {
                            weekday: "long",
                            month: "long",
                            day: "numeric",
                            year: "numeric",
                          })}
                        </h3>
                        <button
                          type="button"
                          className="modal-close"
                          onClick={() => setSelectedDate(null)}
                          aria-label="Close"
                        >
                          ×
                        </button>
                      </div>
                      <div className="modal-body">
                        {getWeeklyTimesForDate(selectedDate, schedules).length > 0 && (
                          <div className="date-editor-section">
                            <span className="date-editor-section-label">From weekly schedule</span>
                            <div className="date-editor-times date-editor-times--readonly">
                              {getWeeklyTimesForDate(selectedDate, schedules).map((time, i) => (
                                <span key={i} className="time-chip">{time}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        <div className="date-editor-section">
                          <span className="date-editor-section-label">This day only</span>
                          <div className="day-times">
                            {(dateEvents[selectedDate] ?? []).map((time, i) => (
                              <div key={i} className="time-slot">
                                <span className="time-value">{time}</span>
                                <button
                                  type="button"
                                  className="time-remove"
                                  onClick={() => {
                                    setDateEvents((prev) => {
                                      const list = (prev[selectedDate] ?? []).filter((_, j) => j !== i);
                                      const next = { ...prev };
                                      if (list.length === 0) delete next[selectedDate];
                                      else next[selectedDate] = list;
                                      return next;
                                    });
                                  }}
                                  aria-label={`Remove ${time}`}
                                >
                                  ×
                                </button>
                              </div>
                            ))}
                            <div className="day-add">
                              <input
                                type="time"
                                className="time-input"
                                onChange={(e) => {
                                  const v = e.target.value;
                                  if (v) {
                                    setDateEvents((prev) => {
                                      const list = prev[selectedDate] ?? [];
                                      if (list.includes(v)) return prev;
                                      return { ...prev, [selectedDate]: [...list, v].sort() };
                                    });
                                    e.target.value = "";
                                  }
                                }}
                                aria-label="Add watering time"
                              />
                              <span className="add-hint">Add time</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
