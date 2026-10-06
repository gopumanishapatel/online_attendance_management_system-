import calendar
import math
import random
from datetime import date, timedelta

import ollama
import pandas as pd
import plotly.express as px
import streamlit as st
from fpdf import FPDF

st.set_page_config(page_title="Attendance System", page_icon="🎓", layout="wide")

FILE = "attendance.csv"
COLUMNS = ["Date", "Roll No", "Name", "Status"]
AI_MODEL = "llama3.2"            # the app also works with any other model you have installed
SAMPLE_GOOD_COUNT = 15           # sample data: this many students stay above 75% every month

# ---------- USERNAMES AND PASSWORDS (change these!) ----------
USERS = {
    "admin": "admin123",
    "teacher1": "teach@123",
    "teacher2": "teach@456",
    "hod": "hod@123",
    "staff": "staff@123",
}

# ---------- STUDENTS: only these students can have attendance ----------
STUDENTS = {
    "25RH1A0501": "Anitha",
    "25RH1A0502": "Ravi",
    "25RH1A0503": "Sneha",
    "25RH1A0504": "Arjun",
    "25RH1A0505": "Priya",
    "25RH1A0506": "Kiran",
    "25RH1A0507": "Divya",
    "25RH1A0508": "Rahul",
    "25RH1A0509": "Meena",
    "25RH1A0510": "Suresh",
    "25RH1A0511": "Lakshmi",
    "25RH1A0512": "Venkat",
    "25RH1A0513": "Pooja",
    "25RH1A0514": "Naveen",
    "25RH1A0515": "Harini",
    "25RH1A0516": "Charan",
    "25RH1A0517": "Swathi",
    "25RH1A0518": "Teja",
    "25RH1A0519": "Bhavana",
    "25RH1A0520": "Sai",
}
LABELS = {f"{roll} - {name}": roll for roll, name in STUDENTS.items()}   # label -> roll no

# ---------- HOLIDAYS ----------
# Fixed-date holidays repeat every year. Format: (month, day): "Name"
FIXED_HOLIDAYS = {
    (1, 1): "New Year's Day",
    (1, 26): "Republic Day",
    (8, 15): "Independence Day",
    (10, 2): "Gandhi Jayanti",
    (12, 25): "Christmas",
}
# Festival holidays that change every year. Format: "YYYY-MM-DD": "Name"
EXTRA_HOLIDAYS = {
    # "2026-11-08": "Diwali",
}


def holiday_name(day):
    """Return the holiday name for a date (Sundays count too), or None for a working day."""
    if day.weekday() == 6:
        return "Sunday"
    if str(day) in EXTRA_HOLIDAYS:
        return EXTRA_HOLIDAYS[str(day)]
    return FIXED_HOLIDAYS.get((day.month, day.day))


def mark_holidays(frame):
    """Change the Status of any record that falls on a holiday to 'Holiday'."""
    if frame.empty:
        return frame
    frame = frame.copy()
    is_hol = pd.to_datetime(frame["Date"]).apply(lambda d: holiday_name(d.date()) is not None)
    frame.loc[is_hol, "Status"] = "Holiday"
    return frame


# ---------- SESSION SETTINGS ----------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "grid_version" not in st.session_state:
    st.session_state.grid_version = 0      # changes when attendance is cleared, so the grid resets

# ---------- LOGIN ----------
if not st.session_state.logged_in:
    st.title("🎓 Attendance Management System")
    st.subheader("🔐 Login")
    with st.form("login"):
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if pwd != "" and USERS.get(user.strip()) == pwd:
                st.session_state.logged_in = True
                st.session_state.user = user.strip()
                st.rerun()
            else:
                st.error("Wrong username or password")
    st.stop()


# ---------- LOAD DATA ----------
try:
    data = pd.read_csv(FILE)
except FileNotFoundError:
    data = pd.DataFrame(columns=COLUMNS)

# Old files without a Roll No column: fill it in from the student names
if "Roll No" not in data.columns:
    name_to_roll = {name: roll for roll, name in STUDENTS.items()}
    data["Roll No"] = data["Name"].map(name_to_roll).fillna("-")

# Remove names that are not in the STUDENTS list (for example names typed without a roll number)
rows_before = len(data)
data = data[data["Roll No"].isin(STUDENTS.keys())].copy()
data["Name"] = data["Roll No"].map(STUDENTS)
data = data[COLUMNS].drop_duplicates(subset=["Date", "Roll No"], keep="last")
data = mark_holidays(data)                      # Sundays and holidays become 'Holiday'
data = data.reset_index(drop=True)
if len(data) != rows_before:
    data.to_csv(FILE, index=False)              # save the cleaned file

# Copy used for reports (adds real dates and a Month column)
df = data.copy()
df["Date"] = pd.to_datetime(df["Date"])
df["Month"] = df["Date"].dt.strftime("%Y-%m")


# ---------- HELPER FUNCTIONS ----------
def find_student(text):
    """Return the roll number if the typed name or roll number exists, else None."""
    text = text.strip().lower()
    for roll, name in STUDENTS.items():
        if text == roll.lower() or text == name.lower():
            return roll
    return None


def summary_from_records(subset):
    """Present / Absent / Working Days / Attendance % for each student (holidays not counted)."""
    work = subset[subset["Status"] != "Holiday"]
    if work.empty:
        return pd.DataFrame(columns=["Roll No", "Name", "Present", "Absent", "Working Days", "Attendance %"])
    grouped = work.groupby(["Roll No", "Name"])["Status"]
    out = pd.DataFrame({
        "Present": grouped.apply(lambda s: int((s == "Present").sum())),
        "Absent": grouped.apply(lambda s: int((s == "Absent").sum())),
    }).reset_index()
    out["Working Days"] = out["Present"] + out["Absent"]
    out["Attendance %"] = (out["Present"] / out["Working Days"] * 100).round(1)
    return out.sort_values("Roll No").reset_index(drop=True)


def color_percent(value):
    return "color: #ff4b4b; font-weight: bold" if value < 75 else "color: #21c354; font-weight: bold"


def colored_table(summary):
    """Red for low attendance, green for good attendance."""
    styler = summary.style.format({"Attendance %": "{:.1f}"})
    try:
        return styler.map(color_percent, subset=["Attendance %"])
    except AttributeError:                       # older pandas
        return styler.applymap(color_percent, subset=["Attendance %"])


def pie_chart(subset, title):
    """Present vs Absent pie chart (holidays are not counted)."""
    subset = subset[subset["Status"] != "Holiday"]
    if subset.empty:
        st.info("No attendance to show")
        return
    counts = subset["Status"].value_counts()
    fig = px.pie(names=counts.index, values=counts.values, title=title,
                 color=counts.index,
                 color_discrete_map={"Present": "#21c354", "Absent": "#ff4b4b"})
    st.plotly_chart(fig, use_container_width=True)


# ---------- PDF ----------
def pdf_text(value):
    """fpdf's built-in font only supports Latin-1 characters."""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def make_pdf(title, subtitle, headers, rows, widths, size=9):
    """Build a landscape A4 PDF with one table and return it as bytes."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, pdf_text(title))
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, pdf_text(subtitle))
    pdf.ln(10)

    def print_header():
        pdf.set_font("Helvetica", "B", size)
        pdf.set_fill_color(225, 225, 250)
        pdf.set_text_color(0, 0, 0)
        for h, w in zip(headers, widths):
            pdf.cell(w, 8, pdf_text(h), border=1, align="C", fill=True)
        pdf.ln(8)
        pdf.set_font("Helvetica", "", size)

    print_header()
    for row in rows:
        if pdf.get_y() > pdf.h - 20:
            pdf.add_page()
            print_header()
        for i, (value, w) in enumerate(zip(row, widths)):
            low = False
            if i == len(row) - 1 and headers[-1] in ("Attendance %", "%"):
                try:
                    low = float(value) < 75
                except ValueError:
                    low = False
            if low:
                pdf.set_text_color(200, 0, 0)      # red for attendance below 75%
            else:
                pdf.set_text_color(0, 0, 0)
            pdf.cell(w, 7, pdf_text(value), border=1, align="C")
        pdf.ln(7)
    pdf.set_text_color(0, 0, 0)
    return bytes(pdf.output())


def summary_pdf(subset, title):
    """PDF with every student's attendance summary for the given records."""
    summary = summary_from_records(subset)
    if summary.empty:
        return None
    headers = ["Roll No", "Name", "Present", "Absent", "Working Days", "Attendance %"]
    rows = summary[headers].values.tolist()
    widths = [40, 60, 35, 35, 45, 45]
    return make_pdf(title, f"Generated on {date.today()}", headers, rows, widths)


def register_pdf(title, register_rows, days_in_month):
    """Classic monthly attendance register: P = present, A = absent, H = holiday."""
    headers = ["Roll No", "Name"] + [str(d) for d in range(1, days_in_month + 1)] + ["P", "%"]
    day_w = (277 - 27 - 28 - 12 - 14) / days_in_month
    widths = [27, 28] + [day_w] * days_in_month + [12, 14]
    subtitle = f"P = Present, A = Absent, H = Holiday / Sunday. Generated on {date.today()}"
    return make_pdf(title, subtitle, headers, register_rows, widths, size=7)


# ---------- REPORT PAGES ----------
def show_summary(summary):
    """Cards, colours, progress bars and tabs for the monthly summary."""
    low = summary[summary["Attendance %"] < 75]

    c1, c2, c3 = st.columns(3)
    c1.metric("👩‍🎓 Total Students", len(summary))
    c2.metric("📈 Average Attendance", f"{summary['Attendance %'].mean():.1f}%")
    c3.metric("⚠️ Below 75%", len(low))

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Table", "📶 Progress", "📊 Chart", "⚠️ Low Attendance"])
    with tab1:
        st.dataframe(colored_table(summary), use_container_width=True, hide_index=True)
    with tab2:
        st.dataframe(
            summary, use_container_width=True, hide_index=True,
            column_config={"Attendance %": st.column_config.ProgressColumn(
                "Attendance %", min_value=0, max_value=100, format="%.1f%%")},
        )
    with tab3:
        st.bar_chart(summary.set_index("Roll No")["Attendance %"])
    with tab4:
        if low.empty:
            st.success("Everyone is above 75% 🎉")
        else:
            st.dataframe(colored_table(low), use_container_width=True, hide_index=True)


def show_report(subset, file_name, title):
    """Records, attendance %, pie chart and CSV / PDF download buttons for any period."""
    if subset.empty:
        st.info("No records for this period")
        return
    table = subset[COLUMNS].copy()
    table["Date"] = table["Date"].dt.date
    summary = summary_from_records(subset)

    tab1, tab2, tab3 = st.tabs(["📋 Records", "📊 Attendance %", "🥧 Present vs Absent"])
    with tab1:
        st.dataframe(table, use_container_width=True, hide_index=True)
    with tab2:
        if summary.empty:
            st.info("Only holidays in this period")
        else:
            st.dataframe(colored_table(summary), use_container_width=True, hide_index=True)
            st.bar_chart(summary.set_index("Roll No")["Attendance %"])
    with tab3:
        pie_chart(subset, "Class attendance")

    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Download CSV", table.to_csv(index=False), f"{file_name}.csv", "text/csv")
    pdf = summary_pdf(subset, title)
    if pdf:
        b2.download_button("📄 Download PDF", pdf, f"{file_name}.pdf", "application/pdf")


# ---------- OLLAMA (AI) ----------
def get_installed_models():
    """List the models installed in Ollama. Raises an error if Ollama is not running."""
    response = ollama.list()
    models = response["models"] if isinstance(response, dict) else getattr(response, "models", [])
    names = []
    for m in models:
        if isinstance(m, dict):
            name = m.get("model") or m.get("name")
        else:
            name = getattr(m, "model", None) or getattr(m, "name", None)
        if name:
            names.append(name)
    return names


def pick_model():
    """Use AI_MODEL if it is installed, otherwise the first installed model."""
    names = get_installed_models()
    if not names:
        raise RuntimeError(f"No model is installed in Ollama. Run this in a terminal: ollama pull {AI_MODEL}")
    for n in names:
        if n == AI_MODEL or n.startswith(AI_MODEL + ":"):
            return n
    return names[0]


def ask_ai(messages):
    model = pick_model()
    reply = ollama.chat(model=model, messages=messages, options={"num_ctx": 4096})
    return reply["message"]["content"]


def ai_error_text(e):
    text = str(e)
    if isinstance(e, RuntimeError):
        return text
    if "connect" in text.lower() or "refused" in text.lower():
        return "Ollama is not running. Open the Ollama app (or run `ollama serve` in a terminal) and try again."
    if "not found" in text.lower():
        return f"The model was not found. Run `ollama pull {AI_MODEL}` in a terminal and try again."
    return f"AI error: {text}"


def build_ai_context():
    """A short summary of the attendance (the AI cannot read thousands of rows)."""
    work = df[df["Status"] != "Holiday"].copy()
    if work.empty:
        return None
    overall = summary_from_records(work)
    work["Percent"] = (work["Status"] == "Present") * 100
    monthly = work.pivot_table(index=["Roll No", "Name"], columns="Month",
                               values="Percent", aggfunc="mean").round(1)
    return (
        f"Today is {date.today()}. Sundays and holidays are not counted.\n\n"
        f"OVERALL ATTENDANCE PER STUDENT:\n{overall.to_string(index=False)}\n\n"
        f"MONTHLY ATTENDANCE % PER STUDENT (columns are year-month):\n{monthly.to_string()}"
    )


# ---------- SAMPLE DATA ----------
def make_sample_data(existing):
    """Sample attendance from January to today. 15 students stay above 75% in every month."""
    today = date.today()
    start = date(today.year, 1, 1)
    rolls = list(STUDENTS.keys())
    rng = random.Random(7)                                     # same sample every time
    good = set(rng.sample(rolls, min(SAMPLE_GOOD_COUNT, len(rolls))))

    rows = []
    for m in range(1, today.month + 1):
        last = today.day if m == today.month else calendar.monthrange(today.year, m)[1]
        all_days = [date(today.year, m, d) for d in range(1, last + 1)]
        working = [d for d in all_days if holiday_name(d) is None]
        n = len(working)
        for roll, name in STUDENTS.items():
            if n == 0:
                absent_days = set()
            elif roll in good:
                max_abs = math.ceil(n * 0.25) - 1               # most absences that still keep % above 75
                absent_days = set(rng.sample(working, rng.randint(max(0, max_abs - 3), max_abs)))
            else:
                min_abs = n // 4 + 1                            # fewest absences that put % below 75
                absent_days = set(rng.sample(working, min(n, rng.randint(min_abs, min_abs + max(1, n // 6)))))
            for day in all_days:
                if holiday_name(day):
                    status = "Holiday"
                else:
                    status = "Absent" if day in absent_days else "Present"
                rows.append([str(day), roll, name, status])

    dates = pd.to_datetime(existing["Date"])
    old = (dates >= pd.Timestamp(start)) & existing["Roll No"].isin(STUDENTS.keys())
    return pd.concat([existing[~old], pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)


# ---------- TITLE AND SIDEBAR ----------
st.title("🎓 Attendance Management System")
st.caption("Track daily, weekly and monthly attendance. Sundays and holidays are marked automatically.")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

st.sidebar.title("📌 Menu")
st.sidebar.write(f"👤 Logged in as: **{st.session_state.user}**")
menu = st.sidebar.radio("Go to", [
    "📅 Monthly Attendance", "📝 Mark Attendance", "👤 Student Profile",
    "📋 All Records", "🗓️ Weekly Report", "📆 Monthly Report", "🤖 Ask AI",
])
if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.rerun()

with st.sidebar.expander("🛠️ Admin tools"):
    st.caption("Demo data: 15 students above 75% in every month, the rest below 75%. "
               "It replaces this year's records of these students.")
    if st.button("🧪 Load sample attendance"):
        make_sample_data(data).to_csv(FILE, index=False)
        st.session_state.grid_version += 1
        st.session_state.flash = "Sample attendance loaded ✅"
        st.rerun()

    st.divider()
    with st.form("clear_all_form", clear_on_submit=True):
        sure_all = st.checkbox("Yes, delete ALL saved attendance")
        if st.form_submit_button("🗑️ Clear ALL attendance"):
            if sure_all:
                pd.DataFrame(columns=COLUMNS).to_csv(FILE, index=False)
                st.session_state.grid_version += 1
                st.session_state.flash = "All attendance cleared 🗑️"
                st.rerun()
            else:
                st.warning("Tick the box first")


# ---------- 1. MONTHLY ATTENDANCE ----------
if menu == "📅 Monthly Attendance":
    today = date.today()
    col1, col2 = st.columns(2)
    year = col1.selectbox("Year", [today.year - 1, today.year, today.year + 1], index=1)
    month = col2.selectbox(
        "Month", list(range(1, 13)), index=today.month - 1,
        format_func=lambda m: calendar.month_name[m],
    )
    days_in_month = calendar.monthrange(year, month)[1]

    # Holidays of this month
    month_holidays = {}
    for d in range(1, days_in_month + 1):
        name = holiday_name(date(year, month, d))
        if name:
            month_holidays[d] = name

    top = st.container()   # summary is filled in here, above the grid

    # Build the grid (all unticked), then tick the days already saved as Present
    grid = pd.DataFrame(False, index=list(LABELS.keys()),
                        columns=[str(d) for d in range(1, days_in_month + 1)])
    saved = df[(df["Date"].dt.year == year) & (df["Date"].dt.month == month)
               & (df["Status"] == "Present")]
    for _, row in saved.iterrows():
        label = f"{row['Roll No']} - {row['Name']}"
        if label in grid.index:
            grid.loc[label, str(row["Date"].day)] = True

    # Column headers show the weekday; holiday columns are locked and marked
    column_config = {}
    for d in range(1, days_in_month + 1):
        weekday = calendar.day_abbr[date(year, month, d).weekday()]
        if d in month_holidays:
            column_config[str(d)] = st.column_config.CheckboxColumn(
                f"{d} {weekday} 🏖️", disabled=True, help=month_holidays[d])
        else:
            column_config[str(d)] = st.column_config.CheckboxColumn(f"{d} {weekday}")

    st.subheader("✅ Mark Attendance")
    st.caption("Tick a box to mark Present, then click Save Attendance. "
               "Unticked past days count as Absent. 🏖️ columns are holidays and are locked.")
    edited = st.data_editor(
        grid, use_container_width=True, column_config=column_config,
        key=f"grid_{year}_{month}_{st.session_state.grid_version}",
    )

    # Working days counted (holidays are skipped; the current month counts up to today)
    if (year, month) < (today.year, today.month):
        last_day = days_in_month
    elif (year, month) == (today.year, today.month):
        last_day = today.day
    else:
        last_day = 0
    working_days = [d for d in range(1, last_day + 1) if d not in month_holidays]

    # Monthly register rows for the PDF (P / A / H)
    register_rows = []
    for roll, name in STUDENTS.items():
        label = f"{roll} - {name}"
        marks, present_count = [], 0
        for d in range(1, days_in_month + 1):
            day = date(year, month, d)
            if d in month_holidays:
                marks.append("H")
            elif edited.loc[label, str(d)]:
                marks.append("P")
                present_count += 1
            elif day <= today:
                marks.append("A")
            else:
                marks.append("")
        pct = round(present_count / len(working_days) * 100, 1) if working_days else 0.0
        register_rows.append([roll, name] + marks + [present_count, pct])

    with top:
        st.subheader("📊 Monthly Attendance % (every student)")
        if len(working_days) == 0:
            st.info("No working days counted yet for this month")
        else:
            present_days = edited[[str(d) for d in working_days]].sum(axis=1)
            summary = pd.DataFrame({
                "Roll No": list(STUDENTS.keys()),
                "Name": list(STUDENTS.values()),
                "Present Days": present_days.values,
                "Working Days": len(working_days),
                "Attendance %": (present_days.values / len(working_days) * 100).round(1),
            })
            show_summary(summary)

            d1, d2 = st.columns(2)
            d1.download_button(
                "⬇️ Download summary (CSV)", summary.to_csv(index=False),
                f"attendance_{year}_{month:02d}.csv", "text/csv",
            )
            pdf = register_pdf(f"Attendance Register - {calendar.month_name[month]} {year}",
                               register_rows, days_in_month)
            d2.download_button(
                "📄 Download register (PDF)", pdf,
                f"attendance_{year}_{month:02d}.pdf", "application/pdf",
            )

            if st.button("🤖 Generate AI summary"):
                prompt = (
                    f"Attendance summary for {calendar.month_name[month]} {year} "
                    f"(Sundays and holidays are not counted):\n"
                    f"{summary.to_string(index=False)}\n\n"
                    "Write a short report for the teacher in 4 to 5 lines. "
                    "Mention who has the best attendance and which students are at risk (below 75%)."
                )
                try:
                    with st.spinner("AI is writing the summary..."):
                        st.info(ask_ai([{"role": "user", "content": prompt}]))
                except Exception as e:
                    st.error(ai_error_text(e))

    # Save button
    if st.button("💾 Save Attendance"):
        new_rows = []
        for roll, name in STUDENTS.items():
            label = f"{roll} - {name}"
            for d in range(1, days_in_month + 1):
                day = date(year, month, d)
                if d in month_holidays:
                    new_rows.append([str(day), roll, name, "Holiday"])
                elif edited.loc[label, str(d)]:
                    new_rows.append([str(day), roll, name, "Present"])
                elif day <= today:
                    new_rows.append([str(day), roll, name, "Absent"])
        dates = pd.to_datetime(data["Date"])
        in_month = (dates.dt.year == year) & (dates.dt.month == month)
        data = pd.concat([data[~in_month], pd.DataFrame(new_rows, columns=COLUMNS)], ignore_index=True)
        data.to_csv(FILE, index=False)
        st.success("Attendance saved ✅ (holidays marked automatically)")

    # Clear button for mistakes
    with st.expander("🗑️ Clear attendance (fix a mistake)"):
        st.caption(f"Removes the saved attendance of {calendar.month_name[month]} {year} so you can mark it again.")
        who = st.selectbox("Clear for", ["All students"] + list(LABELS.keys()), key="clear_who")
        with st.form("clear_month_form", clear_on_submit=True):
            sure = st.checkbox("Yes, I want to clear it")
            go = st.form_submit_button("🗑️ Clear attendance")
        if go:
            if not sure:
                st.warning("Tick 'Yes, I want to clear it' first.")
            else:
                dates = pd.to_datetime(data["Date"])
                in_month = (dates.dt.year == year) & (dates.dt.month == month)
                if who != "All students":
                    in_month = in_month & (data["Roll No"] == LABELS[who])
                data = data[~in_month]
                data.to_csv(FILE, index=False)
                st.session_state.grid_version += 1
                st.session_state.flash = f"Cleared attendance for {who} ({calendar.month_name[month]} {year}) 🗑️"
                st.rerun()


# ---------- 2. MARK ATTENDANCE (only existing students, not on holidays) ----------
elif menu == "📝 Mark Attendance":
    st.subheader("📝 Mark Attendance")
    typed = st.text_input("Enter student name or roll number")
    day = st.date_input("Date", date.today())
    status = st.selectbox("Status", ["Present", "Absent"])

    if st.button("Save"):
        roll = find_student(typed)
        hol = holiday_name(day)
        if roll is None:
            st.error(f"'{typed}' does not exist. Please enter a name or roll number from the list below.")
        elif hol is not None:
            st.warning(f"{day} is a holiday ({hol}). Attendance cannot be marked on a holiday.")
        else:
            data = data[~((data["Roll No"] == roll) & (data["Date"] == str(day)))]
            new_row = pd.DataFrame([[str(day), roll, STUDENTS[roll], status]], columns=COLUMNS)
            data = pd.concat([data, new_row], ignore_index=True)
            data.to_csv(FILE, index=False)
            st.success(f"Saved: {roll} - {STUDENTS[roll]} is {status} on {day}")

            mine = data[(data["Roll No"] == roll) & (data["Status"] != "Holiday")]
            percent = round((mine["Status"] == "Present").sum() / len(mine) * 100, 1)
            st.info(f"Overall attendance of {STUDENTS[roll]}: {percent}%")

    with st.expander("See existing students"):
        st.table(pd.DataFrame({"Roll No": list(STUDENTS.keys()), "Name": list(STUDENTS.values())}))

    st.divider()
    st.subheader("🗑️ Clear a wrong entry")
    clear_typed = st.text_input("Student name or roll number", key="clear_typed")
    clear_day = st.date_input("Date to clear", date.today(), key="clear_day")
    if st.button("🗑️ Clear this entry"):
        roll = find_student(clear_typed)
        if roll is None:
            st.error(f"'{clear_typed}' does not exist.")
        else:
            mask = (data["Roll No"] == roll) & (data["Date"] == str(clear_day))
            if mask.any():
                data = data[~mask]
                data.to_csv(FILE, index=False)
                st.success(f"Cleared {roll} - {STUDENTS[roll]} on {clear_day}. You can mark it again above.")
            else:
                st.info("No saved attendance found for that student and date.")


# ---------- 3. STUDENT PROFILE ----------
elif menu == "👤 Student Profile":
    st.subheader("👤 Student Profile")
    label = st.selectbox("Choose a student", list(LABELS.keys()))
    roll = LABELS[label]
    mine = df[(df["Roll No"] == roll) & (df["Status"] != "Holiday")]   # holidays not counted

    if mine.empty:
        st.info("No attendance saved for this student yet")
    else:
        present_count = int((mine["Status"] == "Present").sum())
        absent_count = int((mine["Status"] == "Absent").sum())
        percent = round(present_count / len(mine) * 100, 1)

        c1, c2, c3 = st.columns(3)
        c1.metric("Overall Attendance", f"{percent}%")
        c2.metric("Days Present", present_count)
        c3.metric("Days Absent", absent_count)

        left, right = st.columns(2)
        with left:
            st.markdown("**Month-by-month attendance %**")
            monthly = mine.groupby("Month")["Status"].apply(lambda s: round((s == "Present").mean() * 100, 1))
            st.bar_chart(monthly)
        with right:
            pie_chart(mine, "Present vs Absent")

        st.markdown("**Absent dates**")
        absent_dates = mine[mine["Status"] == "Absent"]["Date"].dt.date.tolist()
        if absent_dates:
            st.write(", ".join(str(d) for d in absent_dates))
        else:
            st.success("No absences 🎉")


# ---------- 4. ALL RECORDS ----------
elif menu == "📋 All Records":
    st.subheader("📋 All Records")
    show_report(df, "all_records", "Attendance Report - All Records")


# ---------- 5. WEEKLY REPORT ----------
elif menu == "🗓️ Weekly Report":
    st.subheader("🗓️ Weekly Report")
    pick = st.date_input("Pick any date in the week", date.today())
    start = pick - timedelta(days=pick.weekday())   # Monday
    end = start + timedelta(days=6)                 # Sunday
    st.write(f"Week: **{start}** to **{end}**")
    week_data = df[(df["Date"] >= pd.Timestamp(start)) & (df["Date"] <= pd.Timestamp(end))]
    show_report(week_data, f"week_{start}", f"Weekly Attendance Report ({start} to {end})")


# ---------- 6. MONTHLY REPORT ----------
elif menu == "📆 Monthly Report":
    st.subheader("📆 Monthly Report")
    months = sorted(df["Month"].unique(), reverse=True)
    if len(months) == 0:
        st.info("No attendance saved yet")
    else:
        month_pick = st.selectbox("Choose month", months)
        show_report(df[df["Month"] == month_pick], f"month_{month_pick}",
                    f"Monthly Attendance Report ({month_pick})")


# ---------- 7. ASK AI ----------
else:
    st.subheader("🤖 Attendance Chatbot")

    # Check Ollama and show clear instructions if something is wrong
    try:
        model_in_use = pick_model()
        st.success(f"Ollama is connected. Using model: {model_in_use}")
        ai_ready = True
    except Exception as e:
        st.error(ai_error_text(e))
        st.caption("Steps: 1) Install and open Ollama   2) Run `ollama pull llama3.2` in a terminal   "
                   "3) Come back here and refresh the page.")
        ai_ready = False

    # Quick answers that work even without AI
    st.markdown("**⚡ Quick answers (no AI needed)**")
    overall = summary_from_records(df)
    q1, q2, q3 = st.columns(3)
    if overall.empty:
        st.info("No attendance data yet. Save some attendance or load the sample data from Admin tools.")
    else:
        if q1.button("⚠️ Students below 75%"):
            st.dataframe(colored_table(overall[overall["Attendance %"] < 75]),
                         use_container_width=True, hide_index=True)
        if q2.button("🏆 Top 5 attendance"):
            st.dataframe(colored_table(overall.nlargest(5, "Attendance %")),
                         use_container_width=True, hide_index=True)
        if q3.button("📉 Lowest 5 attendance"):
            st.dataframe(colored_table(overall.nsmallest(5, "Attendance %")),
                         use_container_width=True, hide_index=True)

    st.divider()
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if st.button("🧹 Clear chat"):
        st.session_state.messages = []
        st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    question = st.chat_input("Ask about attendance, e.g. Who has the lowest attendance in September?")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)

        with st.chat_message("assistant"):
            context = build_ai_context()
            if context is None:
                answer = "There is no attendance data yet. Please save some attendance first."
            elif not ai_ready:
                answer = "The AI is not connected yet. Please follow the steps shown above."
            else:
                system = ("You are a helpful assistant for a teacher. Answer only from the attendance "
                          "data below. Keep answers short and clear.\n\n" + context)
                chat = [{"role": "system", "content": system}] + st.session_state.messages[-6:]
                try:
                    with st.spinner("Thinking..."):
                        answer = ask_ai(chat)
                except Exception as e:
                    answer = ai_error_text(e)
            st.write(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})