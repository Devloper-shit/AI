import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import pandas as pd
import traceback
import io
from streamlit_option_menu import option_menu

# -----------------------------
# 1. CONFIGURATION
# -----------------------------
st.set_page_config(page_title="Cambridge Portal", page_icon="🏫", layout="wide")

# Minimal CSS – No animations, clean dark theme
st.markdown("""
<style>
/* Overall */
body {
    background-color: #0f172a;
    color: #e2e8f0;
}
.main {
    background-color: transparent;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #1e293b;
    border-right: 1px solid #334155;
}
section[data-testid="stSidebar"] * {
    color: #cbd5e1 !important;
}

/* Cards */
div[data-testid="stVerticalBlock"] > div {
    background: #1e293b;
    border-radius: 10px;
    border: 1px solid #334155;
    padding: 20px;
    margin-bottom: 16px;
}

/* Buttons */
.stButton > button {
    background-color: #3b82f6;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
}
.stButton > button:hover {
    background-color: #2563eb;
}

/* Inputs */
.stTextInput input, .stNumberInput input, .stSelectbox select {
    background-color: #1e293b !important;
    border: 1px solid #475569 !important;
    border-radius: 6px !important;
    color: white !important;
}

/* Tables */
.stTable tbody tr:nth-child(even) {
    background-color: #1e293b;
}
.stTable tbody tr:hover {
    background-color: #334155;
}

/* Metric Cards */
[data-testid="metric-container"] {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 16px;
}
[data-testid="metric-container"] label {
    color: #94a3b8;
    font-size: 13px;
}
[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #fbbf24;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# 2. LOGIN
# -----------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
    st.session_state["role"] = None

if not st.session_state["authenticated"]:
    _, center, _ = st.columns([1,2,1])
    with center:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center; color:#fbbf24;'>Cambridge International</h2>", unsafe_allow_html=True)
        role = st.selectbox("Select Role", ["Teacher", "Clerk", "Principal"])
        pwd = st.text_input("Password", type="password")
        if st.button("Login"):
            valid = False
            if role == "Teacher" and pwd == "TCH2024": valid = True
            elif role == "Clerk" and pwd == "CLK2024": valid = True
            elif role == "Principal" and pwd == "PRN2024": valid = True
            if valid:
                st.session_state["authenticated"] = True
                st.session_state["role"] = role
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

# -----------------------------
# 3. DATABASE CONNECTION
# -----------------------------
# ⚡ APNI SHEET ID YAHAN DAALO
SHEET_ID = "d/1-U9d-zMbo7g6_qoQY_trLkZNRpwTK1Em7Q982Hmx5RA/edit?gid=0#gid=0"

@st.cache_resource
def get_workbook():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["gcp_service_account"]), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None

wb = get_workbook()
if wb is None: st.stop()

# -----------------------------
# 4. CACHING FUNCTIONS
# -----------------------------
@st.cache_data(ttl=600)
def get_sheet_names():
    return [ws.title.strip() for ws in wb.worksheets()]

def find_sheet(name):
    names = get_sheet_names()
    name_clean = name.strip().lower()
    for n in names:
        if n.lower() == name_clean: return wb.worksheet(n)
    for n in names:
        if name_clean in n.lower(): return wb.worksheet(n)
    return None

# Extract class names from master sheets (e.g., "MASTER_LKG" -> "LKG")
def get_available_classes():
    sheets = get_sheet_names()
    classes = []
    for s in sheets:
        if s.upper().startswith("MASTER_"):
            class_name = s.split("_", 1)[1].strip()
            if class_name:
                classes.append(class_name)
    return sorted(classes) if classes else ["LKG"]

@st.cache_data(ttl=600)
def load_master_data(class_name):
    sheet = find_sheet(f"MASTER_{class_name}")
    if not sheet: return pd.DataFrame(), []
    raw = sheet.get_all_values()
    if len(raw) < 2: return pd.DataFrame(), []
    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)
    # Find ID and Name columns (case‑insensitive)
    id_col = next((c for c in df.columns if c.upper() in ['ID', 'STUDENT ID', 'STUDENT_ID']), None)
    name_col = next((c for c in df.columns if c.upper() in ['NAME', 'STUDENT NAME']), None)
    student_list = []
    if id_col and name_col:
        student_list = [f"{row[id_col]} - {row[name_col]}" for _, row in df.iterrows()]
    return df, student_list

@st.cache_data(ttl=600)
def load_attendance_data(class_name):
    sheet = find_sheet(f"ATTENDANCE_{class_name}")
    return sheet.get_all_values() if sheet else []

@st.cache_data(ttl=600)
def load_fees_data(class_name):
    sheet = find_sheet(f"FEES_{class_name}")
    return sheet.get_all_values() if sheet else []

@st.cache_data(ttl=600)
def load_fee_structure():
    sheet = find_sheet("FEES_STRUCTURE")
    if not sheet: return {}
    data = sheet.get_all_values()
    fee_map = {}
    if len(data) >= 2:
        for row in data[1:]:
            if len(row) >= 2:
                cls, fee = row[0].strip(), row[1].strip()
                if cls and fee.isdigit(): fee_map[cls] = int(fee)
    return fee_map

# -----------------------------
# 5. SIDEBAR – All navigation
# -----------------------------
with st.sidebar:
    st.header("Administration")
    st.markdown(f"**{st.session_state['role']}**")

    available_classes = get_available_classes()
    selected_class = st.selectbox("Class", available_classes)

    role = st.session_state["role"]
    if role == "Teacher":
        menu_options = ["Student Attendance", "Attendance Report", "Student Records", "Edit Student Details", "Add New Student", "At-Risk Students"]
    elif role == "Clerk":
        menu_options = ["Fee Collection", "Daily Cash Report", "Defaulter List", "Add New Student", "Student Records"]
    else:  # Principal
        menu_options = ["Executive Dashboard", "Student Attendance", "Attendance Report", "Fee Collection", "Daily Cash Report", "Defaulter List", "Student Records", "Edit Student Details", "Add New Student", "At-Risk Students"]

    icons = {
        "Executive Dashboard": "speedometer2", "Student Attendance": "calendar-check",
        "Attendance Report": "bar-chart-line", "Fee Collection": "cash-stack",
        "Daily Cash Report": "graph-up-arrow", "Defaulter List": "exclamation-triangle",
        "Student Records": "people", "Edit Student Details": "pencil-square",
        "Add New Student": "person-plus", "At-Risk Students": "exclamation-circle"
    }
    menu = option_menu(None, menu_options, [icons.get(o,"circle") for o in menu_options],
        menu_icon="cast", default_index=0,
        styles={
            "container": {"background-color": "#1e293b"},
            "icon": {"color": "#fbbf24"},
            "nav-link": {"--hover-color": "#334155"},
            "nav-link-selected": {"background-color": "#3b82f6"},
        }
    )

    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()
    if st.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

# -----------------------------
# 6. LOAD DATA
# -----------------------------
df_master, student_list = load_master_data(selected_class)
id_col = next((c for c in df_master.columns if c.upper() in ['ID', 'STUDENT ID']), None) if not df_master.empty else None
name_col = next((c for c in df_master.columns if c.upper() in ['NAME', 'STUDENT NAME']), None) if not df_master.empty else None

attendance_data = load_attendance_data(selected_class)
fees_data = load_fees_data(selected_class)
monthly_fee_map = load_fee_structure()
default_fee = monthly_fee_map.get(selected_class, 500)

# Get sheet objects
master_sheet = find_sheet(f"MASTER_{selected_class}")
attendance_sheet = find_sheet(f"ATTENDANCE_{selected_class}")
fees_sheet = find_sheet(f"FEES_{selected_class}")
if not all([master_sheet, attendance_sheet, fees_sheet]):
    st.error("Required sheets missing.")
    st.stop()

# Utility: Ensure a column exists in master (add if not)
def ensure_column(sheet, col_name):
    headers = sheet.row_values(1)
    if col_name not in headers:
        sheet.update_cell(1, len(headers)+1, col_name)
        st.cache_data.clear()

# Ensure Total_Fees column exists (column G traditionally)
ensure_column(master_sheet, "Total_Fees")

# -----------------------------
# 7. BRANDING
# -----------------------------
st.markdown("<h2 style='text-align:center; color:#fbbf24;'>CAMBRIDGE INTERNATIONAL</h2>", unsafe_allow_html=True)
st.divider()

# =============================
# 8. EXECUTIVE DASHBOARD
# =============================
if menu == "Executive Dashboard" and role == "Principal":
    st.subheader(f"Dashboard – {selected_class}")
    if df_master.empty:
        st.warning("No student data.")
    else:
        total = len(df_master)
        today_str = datetime.now().strftime("%d-%m-%Y")
        att_headers = attendance_data[0] if attendance_data else []
        today_col = att_headers.index(today_str)+1 if today_str in att_headers else None
        present = 0
        if today_col and len(attendance_data)>1:
            for row in attendance_data[1:]:
                if today_col < len(row) and row[today_col].strip().upper() == 'P':
                    present += 1
        att_pct = (present/total*100) if total else 0

        today_fees = 0
        if fees_data and len(fees_data)>1:
            for r in fees_data[1:]:
                if len(r)>=4 and r[3].split(' ')[0] == today_str and r[1].isdigit():
                    today_fees += int(r[1])

        current_month = datetime.now().month
        current_year = datetime.now().year
        month_col = 0
        if fees_data and len(fees_data)>1:
            for r in fees_data[1:]:
                if len(r)>=4:
                    ds = r[3].split(' ')[0]
                    try:
                        d = datetime.strptime(ds, "%d-%m-%Y")
                        if d.month == current_month and d.year == current_year and r[1].isdigit():
                            month_col += int(r[1])
                    except: pass

        monthly_fee = monthly_fee_map.get(selected_class, 500)
        expected_monthly = total * monthly_fee
        col_pct = (month_col/expected_monthly*100) if expected_monthly else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Students", total)
        col2.metric("Today Att.", f"{att_pct:.0f}% ({present}/{total})")
        col3.metric("Today Fees", f"₹{today_fees}")
        col4.metric("Month Fees", f"₹{month_col} ({col_pct:.0f}%)")

        # Top Defaulters
        if not df_master.empty and 'Total_Fees' in df_master.columns:
            def calc(row):
                paid = int(row['Total_Fees']) if str(row['Total_Fees']).isdigit() else 0
                if current_month>=4: months = current_month-4+1
                else: months = current_month+9
                expected = months * monthly_fee
                return max(0, expected - paid)
            df_master['Outstanding'] = df_master.apply(calc, axis=1)
            top5 = df_master.nlargest(5, 'Outstanding')[['Name', 'Outstanding']] if 'Name' in df_master.columns else df_master.nlargest(5, 'Outstanding').iloc[:,:2]
        else:
            top5 = pd.DataFrame()
        st.write("**Top 5 Defaulters**")
        if not top5.empty: st.dataframe(top5)
        else: st.write("No data")

# =============================
# 9. STUDENT ATTENDANCE (same logic, adapted for any class)
# =============================
elif menu == "Student Attendance":
    st.subheader(f"Daily Attendance – {selected_class}")
    if not student_list:
        st.warning("No students.")
    else:
        sel = st.selectbox("Select Student", ["-- Select --"] + student_list)
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Mark Present"):
                if sel != "-- Select --":
                    sid = sel.split(" - ")[0]
                    try:
                        today = datetime.now().strftime("%d-%m-%Y")
                        hdrs = attendance_sheet.row_values(1)
                        ci = hdrs.index(today)+1 if today in hdrs else len(hdrs)+1
                        if today not in hdrs: attendance_sheet.update_cell(1, ci, today)
                        cell = attendance_sheet.find(sid)
                        attendance_sheet.update_cell(cell.row, ci, "P")
                        st.success(f"Marked {sel}")
                        st.cache_data.clear()
                    except Exception as e: st.error(f"Error: {e}")
        with c2:
            if st.button("Mark All Present"):
                try:
                    today = datetime.now().strftime("%d-%m-%Y")
                    hdrs = attendance_sheet.row_values(1)
                    ci = hdrs.index(today)+1 if today in hdrs else len(hdrs)+1
                    if today not in hdrs: attendance_sheet.update_cell(1, ci, today)
                    ids = [f"{row[id_col]}" for _, row in df_master.iterrows()]
                    cnt = 0
                    for sid in ids:
                        try:
                            cell = attendance_sheet.find(sid)
                            attendance_sheet.update_cell(cell.row, ci, "P")
                            cnt += 1
                        except: pass
                    st.success(f"All {cnt} marked")
                    st.cache_data.clear()
                except Exception as e: st.error(f"Error: {e}")
        with c3:
            if st.button("Mark Absent for Unmarked"):
                try:
                    today = datetime.now().strftime("%d-%m-%Y")
                    hdrs = attendance_sheet.row_values(1)
                    if today not in hdrs: st.warning("Column not created.")
                    else:
                        ci = hdrs.index(today)+1
                        ids = [f"{row[id_col]}" for _, row in df_master.iterrows()]
                        ac = 0
                        for sid in ids:
                            try:
                                cell = attendance_sheet.find(sid)
                                val = attendance_sheet.cell(cell.row, ci).value
                                if not val or val.strip()=="":
                                    attendance_sheet.update_cell(cell.row, ci, "A")
                                    ac += 1
                            except: pass
                        st.success(f"Marked {ac} absent")
                        st.cache_data.clear()
                except Exception as e: st.error(f"Error: {e}")

# =============================
# 10. ATTENDANCE REPORT
# =============================
elif menu == "Attendance Report":
    st.subheader(f"Monthly Attendance Report – {selected_class}")
    months = ["January","February","March","April","May","June","July","August","September","October","November","December"]
    sel_month = st.selectbox("Month", months, index=datetime.now().month-1)
    sel_year = st.number_input("Year", 2020,2030, datetime.now().year)
    mn = months.index(sel_month)+1
    ms = f"{mn:02d}"
    if len(attendance_data)<2:
        st.warning("No data.")
    else:
        att_headers = attendance_data[0]
        dcols = []; cidx = []
        for i,h in enumerate(att_headers):
            if i==0: continue
            p = h.split('-')
            if len(p)==3 and p[1]==ms and p[2]==str(sel_year):
                dcols.append(h); cidx.append(i)
        if not dcols:
            st.warning(f"No records for {sel_month} {sel_year}")
        else:
            total_days = len(dcols)
            recs = []
            for row in attendance_data[1:]:
                sid = row[0]
                name = "N/A"
                if not df_master.empty:
                    mask = df_master[id_col].astype(str)==sid
                    if mask.any(): name = df_master.loc[mask, name_col].values[0]
                present = sum(1 for ci in cidx if ci<len(row) and row[ci].strip().upper()=='P')
                pct = (present/total_days*100) if total_days else 0
                recs.append({"Student ID":sid,"Name":name,"Working Days":total_days,"Present":present,"Attendance %":round(pct,1)})
            df_rep = pd.DataFrame(recs)
            def hl(val):
                return 'background-color: #ffcccc' if val<75 else ''
            st.dataframe(df_rep.style.map(hl, subset=['Attendance %']), use_container_width=True)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                df_rep.to_excel(w, index=False, sheet_name='Attendance')
            st.download_button("Download Excel", buf.getvalue(), f"Attendance_{selected_class}_{sel_month}_{sel_year}.xlsx")

# =============================
# 11. FEE COLLECTION (Clerk, Principal)
# =============================
elif menu == "Fee Collection":
    if role not in ["Clerk","Principal"]:
        st.error("Access Denied"); st.stop()
    st.subheader(f"Fee Counter – {selected_class}")
    if not student_list:
        st.warning("No students.")
    else:
        sel = st.selectbox("Select Student", ["-- Select --"]+student_list)
        if sel != "-- Select --":
            sid = sel.split(" - ")[0]
            try:
                mc = master_sheet.find(sid)
                mr = master_sheet.row_values(mc.row)
                # Total_Fees is in column G (index 6). Ensure it exists.
                cur = 0
                if len(mr) >= 7 and str(mr[6]).isdigit(): cur = int(mr[6])
                st.info(f"**Student:** {mr[1]} | **Paid:** ₹{cur}")
                with st.form("fee_form", clear_on_submit=True):
                    amt = st.number_input("Amount", min_value=0)
                    mo = st.selectbox("Month", ["April","May","June","July","August","September","October","November","December","January","February","March"])
                    mode = st.selectbox("Mode", ["Cash","Online","Cheque"])
                    if st.form_submit_button("Process Payment"):
                        new = cur + amt
                        # Update/ensure Total_Fees column
                        master_sheet.update_cell(mc.row, 7, str(new))
                        ts = datetime.now().strftime("%d-%m-%Y %H:%M")
                        fees_sheet.insert_row([sid, amt, mo, f"{ts} {mode}"], index=2)
                        st.success(f"Paid ₹{amt}, New Total ₹{new}")
                        st.cache_data.clear()
            except Exception as e: st.error(f"Error: {e}")

# =============================
# 12. DAILY CASH REPORT
# =============================
elif menu == "Daily Cash Report":
    if role not in ["Clerk","Principal"]:
        st.error("Access Denied"); st.stop()
    st.subheader(f"Today's Financial Summary – {selected_class}")
    today_str = datetime.now().strftime("%d-%m-%Y")
    if fees_data and len(fees_data)>1:
        fh = fees_data[0]
        today_rows = [r for r in fees_data[1:] if len(r)>=4 and r[3].split(' ')[0]==today_str]
        if today_rows:
            amt_col = fh.index('Amount') if 'Amount' in fh else 1
            total = sum(int(r[amt_col]) for r in today_rows if r[amt_col].isdigit())
            st.metric("Total Today", f"₹{total}")
            st.dataframe(pd.DataFrame(today_rows, columns=fh)[['Student ID','Amount','Month','Date of payment']])
        else: st.info("No transactions today.")
    else: st.info("No fee records.")

# =============================
# 13. DEFAULTER LIST
# =============================
elif menu == "Defaulter List":
    if role not in ["Clerk","Principal"]:
        st.error("Access Denied"); st.stop()
    st.subheader(f"Fee Defaulter List – {selected_class}")
    if df_master.empty:
        st.warning("No students.")
    else:
        cur_month = datetime.now().month
        if cur_month>=4: mcount = cur_month-4+1
        else: mcount = cur_month+9
        monthly_fee = monthly_fee_map.get(selected_class, 500)
        expected_total = mcount * monthly_fee
        defs = []
        for _, s in df_master.iterrows():
            sid = str(s[id_col])
            name = s[name_col] if name_col else ""
            paid = int(s.get('Total_Fees',0)) if str(s.get('Total_Fees',0)).isdigit() else 0
            out = max(0, expected_total - paid)
            last = "N/A"
            if fees_data:
                for r in fees_data[1:]:
                    if r[0].upper()==sid.upper():
                        ds = r[3] if len(r)>3 else ""
                        if ds: last = ds.split(' ')[0]
            defs.append({"Student ID":sid,"Name":name,"Total Paid":paid,"Expected":expected_total,"Outstanding":out,"Last Paid":last})
        df_def = pd.DataFrame(defs).sort_values("Outstanding", ascending=False)
        def hl(val):
            if val>1000: return 'background-color:#ffcccc'
            elif val>0: return 'background-color:#fff9c4'
            return ''
        st.dataframe(df_def.style.map(hl, subset=['Outstanding']), use_container_width=True)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
            df_def.to_excel(w, index=False)
        st.download_button("Download Excel", buf.getvalue(), f"Defaulters_{selected_class}.xlsx")

# =============================
# 14. STUDENT RECORDS
# =============================
elif menu == "Student Records":
    st.subheader(f"Student Profile – {selected_class}")
    if not student_list:
        st.warning("No students.")
    else:
        sel = st.selectbox("Select Student", ["-- Select --"]+student_list)
        if sel != "-- Select --":
            sid = sel.split(" - ")[0]
            mask = df_master[id_col].astype(str)==sid
            if mask.any():
                sd = df_master[mask].iloc[0]
                name = sd.get(name_col,'')
                roll = sd.get('Roll No','')
                father = sd.get('FATHER','') or sd.get('Father','')
                mobile = sd.get('MOBILE','')
                # Total fees
                total = sd.get('Total_Fees','0')
                addr = sd.get('Address','N/A')
                st.info(f"**{name}** | Roll: {roll}")
                c1,c2 = st.columns(2)
                c1.write(f"Father: {father}")
                c1.write(f"Mobile: {mobile}")
                c2.write(f"Fees Paid: ₹{total}")
                c2.write(f"Address: {addr}")
                st.divider()
                st.subheader("Fee History")
                if fees_data and len(fees_data)>1:
                    fh = fees_data[0]
                    hist = [r for r in fees_data[1:] if r[0].upper()==sid.upper()]
                    if hist:
                        st.table([fh]+hist)
                        df_h = pd.DataFrame(hist, columns=fh)
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                            df_h.to_excel(w, index=False)
                        st.download_button("Download History", buf.getvalue(), f"FeeHistory_{sid}.xlsx")
                    else: st.write("No history.")
                else: st.write("No records.")
            else: st.warning("Not found.")

# =============================
# 15. EDIT STUDENT DETAILS (Dynamic, handles missing columns)
# =============================
elif menu == "Edit Student Details":
    st.subheader(f"Edit Student – {selected_class}")
    if not student_list:
        st.warning("No students.")
    else:
        sel = st.selectbox("Choose Student", ["-- Select --"]+student_list)
        if sel != "-- Select --":
            sid = sel.split(" - ")[0]
            try:
                cell = master_sheet.find(sid)
                rn = cell.row
                rd = master_sheet.row_values(rn)
                hd = [h.strip() for h in master_sheet.row_values(1)]

                def fc(n):   # find column
                    for i,h in enumerate(hd):
                        if h.upper() == n.upper(): return i
                    return None

                # Safely get existing values
                def gv(col): return rd[col] if col is not None and col < len(rd) else ""

                cid = fc('ID') or fc('STUDENT ID')
                cname = fc('NAME')
                cfather = fc('FATHER') or fc('FATHER NAME')
                cmobile = fc('MOBILE')
                caddress = fc('ADDRESS')  # might not exist
                caadhar = fc('AADHAR') or fc('AADHAAR')
                if caddress is None:
                    # add Address column if not present
                    master_sheet.update_cell(1, len(hd)+1, 'Address')
                    st.cache_data.clear()
                    hd.append('Address')
                    caddress = len(hd)-1

                current_name = gv(cname)
                current_father = gv(cfather)
                current_mobile = gv(cmobile)
                current_address = gv(caddress)
                current_aadhaar = gv(caadhar) if caadhar else ""

                st.info(f"**ID:** {sid}")
                with st.form("edit_form"):
                    nn = st.text_input("Name", value=current_name)
                    nf = st.text_input("Father", value=current_father)
                    nm = st.text_input("Mobile", value=current_mobile)
                    na = st.text_input("Address", value=current_address)
                    nd = st.text_input("Aadhaar", value=current_aadhaar)
                    if st.form_submit_button("Update"):
                        if cname: master_sheet.update_cell(rn, cname+1, nn)
                        if cfather: master_sheet.update_cell(rn, cfather+1, nf)
                        if cmobile: master_sheet.update_cell(rn, cmobile+1, nm)
                        master_sheet.update_cell(rn, caddress+1, na)
                        if caadhar: master_sheet.update_cell(rn, caadhar+1, nd)
                        st.success("Updated!")
                        st.cache_data.clear()
            except Exception as e: st.error(f"Error: {e}")

# =============================
# 16. ADD NEW STUDENT
# =============================
elif menu == "Add New Student":
    st.subheader(f"Enroll New Student – {selected_class}")
    existing_ids = []
    existing_rolls = []
    if not df_master.empty and id_col:
        existing_ids = df_master[id_col].astype(str).tolist()
        if 'Roll No' in df_master.columns:
            try: existing_rolls = df_master['Roll No'].astype(int).tolist()
            except: pass
    prefix = f"CME0"
    max_s = 0
    for sid in existing_ids:
        if sid.startswith("CME"):
            num = sid[3:]
            if num.isdigit(): max_s = max(max_s, int(num))
    new_id = f"CME{max_s+1:02d}"
    new_roll = 1 if not existing_rolls else max(existing_rolls)+1

    with st.form("add_student_form", clear_on_submit=True):
        st.info(new_id); st.caption("Auto ID")
        st.info(str(new_roll)); st.caption("Auto Roll")
        nn = st.text_input("Full Name *")
        nf = st.text_input("Father's Name *")
        nm = st.text_input("Mobile")
        na = st.text_input("Address")
        nd = st.text_input("Aadhaar")
        if st.form_submit_button("Enroll"):
            if not nn.strip() or not nf.strip():
                st.error("Name and Father required.")
            else:
                # Prepare row according to existing headers + ensure Total_Fees, Address
                headers = master_sheet.row_values(1)
                row_data = [""]*(len(headers)+3)  # buffer
                def put(col_name, value):
                    if col_name in headers:
                        row_data[headers.index(col_name)] = value
                    else:
                        # add column at end
                        master_sheet.update_cell(1, len(headers)+1, col_name)
                        st.cache_data.clear()
                        headers.append(col_name)
                        row_data.append(value)
                put("ID", new_id)
                put("NAME", nn.strip())
                put("ROLL NO", str(new_roll))
                put("FATHER", nf.strip())
                put("MOBILE", nm.strip() if nm else "")
                put("ADDRESS", na.strip() if na else "")
                put("AADHAR", nd.strip() if nd else "")
                put("Total_Fees", "0")
                # Ensure NODE exists for blank
                if "NODE" not in headers:
                    master_sheet.update_cell(1, len(headers)+1, "NODE")
                    headers.append("NODE")
                # build final row (match column order)
                final_row = []
                for h in headers:
                    if h in ["ID","NAME","ROLL NO","FATHER","NODE","MOBILE","Total_Fees","ADDRESS","AADHAR"]:
                        final_row.append(row_data[headers.index(h)] if h in headers else "")
                    else:
                        final_row.append("")
                master_sheet.append_row(final_row, value_input_option='USER_ENTERED')
                attendance_sheet.append_row([new_id])
                st.success(f"Enrolled {nn}")
                st.balloons()
                st.cache_data.clear()
                st.rerun()

# =============================
# 17. AT-RISK STUDENTS
# =============================
elif menu == "At-Risk Students":
    st.subheader(f"Dropout Risk – {selected_class}")
    if len(attendance_data)<2:
        st.warning("No data.")
    else:
        ah = attendance_data[0]
        dm = {}
        for i,h in enumerate(ah):
            if i==0: continue
            p = h.split('-')
            if len(p)==3:
                try: dm[i] = datetime.strptime(h, "%d-%m-%Y")
                except: pass
        sorted_cols = sorted(dm.items(), key=lambda x: x[1])
        risk = []
        for row in attendance_data[1:]:
            sid = row[0]
            name = "N/A"
            if not df_master.empty and id_col:
                mask = df_master[id_col].astype(str)==sid
                if mask.any(): name = df_master.loc[mask, name_col].values[0] if name_col else ""
            maxc = 0; cur = 0
            for ci,_ in sorted_cols:
                val = row[ci].strip().upper() if ci<len(row) else ""
                if val!='P': cur+=1
                else: cur=0
                maxc = max(maxc, cur)
            if maxc>=5: risk.append((sid, name, maxc))
        if risk:
            df_r = pd.DataFrame(risk, columns=["Student ID","Name","Consecutive Absences"])
            st.warning(f"Total at risk: {len(risk)}")
            st.dataframe(df_r.style.map(lambda x: 'background-color:#ffcccc' if isinstance(x,int) and x>=5 else '', subset=['Consecutive Absences']))
        else: st.success("No student with 5+ consecutive absences.")
