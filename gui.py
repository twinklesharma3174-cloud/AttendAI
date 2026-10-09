import tkinter as tk
from tkinter import messagebox, ttk
import os
import csv
from datetime import datetime

from src.student_registration import StudentRegistration
from src.attendance import AttendanceSystem


class AttendAIGUI:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "AttendAI - Smart Attendance Management"
        )

        self.root.geometry("1000x650")
        self.root.minsize(900, 600)

        self.root.configure(
            bg="#f4f6f8"
        )

        self.create_header()
        self.create_dashboard()
        self.create_footer()

        self.update_statistics()

    # ---------------- HEADER ----------------

    def create_header(self):

        header = tk.Frame(
            self.root,
            bg="#17202a",
            height=90
        )

        header.pack(
            fill="x"
        )

        title = tk.Label(
            header,
            text="AttendAI",
            font=("Segoe UI", 28, "bold"),
            bg="#17202a",
            fg="white"
        )

        title.pack(
            pady=(15, 0)
        )

        subtitle = tk.Label(
            header,
            text="Smart Attendance Management using Facial Recognition",
            font=("Segoe UI", 11),
            bg="#17202a",
            fg="#d5d8dc"
        )

        subtitle.pack()

    # ---------------- DASHBOARD ----------------

    def create_dashboard(self):

        main_frame = tk.Frame(
            self.root,
            bg="#f4f6f8"
        )

        main_frame.pack(
            fill="both",
            expand=True,
            padx=40,
            pady=30
        )

        # Statistics

        stats_frame = tk.Frame(
            main_frame,
            bg="#f4f6f8"
        )

        stats_frame.pack(
            fill="x",
            pady=(0, 25)
        )

        self.students_card = self.create_stat_card(
            stats_frame,
            "REGISTERED STUDENTS",
            "0"
        )

        self.students_card.pack(
            side="left",
            fill="both",
            expand=True,
            padx=8
        )

        self.attendance_card = self.create_stat_card(
            stats_frame,
            "TODAY'S ATTENDANCE",
            "0"
        )

        self.attendance_card.pack(
            side="left",
            fill="both",
            expand=True,
            padx=8
        )

        self.date_card = self.create_stat_card(
            stats_frame,
            "DATE",
            datetime.now().strftime("%d %b %Y")
        )

        self.date_card.pack(
            side="left",
            fill="both",
            expand=True,
            padx=8
        )

        # Buttons

        actions = tk.Frame(
            main_frame,
            bg="#f4f6f8"
        )

        actions.pack(
            pady=20
        )

        register_button = tk.Button(
            actions,
            text="👤  Register Student",
            command=self.register_student,
            font=("Segoe UI", 13, "bold"),
            width=25,
            height=2,
            bg="#3498db",
            fg="white",
            relief="flat",
            cursor="hand2"
        )

        register_button.grid(
            row=0,
            column=0,
            padx=15,
            pady=15
        )

        attendance_button = tk.Button(
            actions,
            text="📷  Start Attendance",
            command=self.start_attendance,
            font=("Segoe UI", 13, "bold"),
            width=25,
            height=2,
            bg="#27ae60",
            fg="white",
            relief="flat",
            cursor="hand2"
        )

        attendance_button.grid(
            row=0,
            column=1,
            padx=15,
            pady=15
        )

        view_button = tk.Button(
            actions,
            text="📊  View Attendance",
            command=self.view_attendance,
            font=("Segoe UI", 13, "bold"),
            width=25,
            height=2,
            bg="#8e44ad",
            fg="white",
            relief="flat",
            cursor="hand2"
        )

        view_button.grid(
            row=1,
            column=0,
            padx=15,
            pady=15
        )

        refresh_button = tk.Button(
            actions,
            text="🔄  Refresh Dashboard",
            command=self.update_statistics,
            font=("Segoe UI", 13, "bold"),
            width=25,
            height=2,
            bg="#f39c12",
            fg="white",
            relief="flat",
            cursor="hand2"
        )

        refresh_button.grid(
            row=1,
            column=1,
            padx=15,
            pady=15
        )

    # ---------------- STAT CARD ----------------

    def create_stat_card(
        self,
        parent,
        title,
        value
    ):

        card = tk.Frame(
            parent,
            bg="white",
            bd=1,
            relief="solid",
            height=110
        )

        title_label = tk.Label(
            card,
            text=title,
            font=("Segoe UI", 10, "bold"),
            bg="white",
            fg="#566573"
        )

        title_label.pack(
            pady=(15, 5)
        )

        value_label = tk.Label(
            card,
            text=value,
            font=("Segoe UI", 20, "bold"),
            bg="white",
            fg="#17202a"
        )

        value_label.pack()

        card.value_label = value_label

        return card

    # ---------------- REGISTER ----------------

    def register_student(self):

        window = tk.Toplevel(
            self.root
        )

        window.title(
            "Register Student"
        )

        window.geometry(
            "400x300"
        )

        window.resizable(
            False,
            False
        )

        tk.Label(
            window,
            text="Student Registration",
            font=("Segoe UI", 18, "bold")
        ).pack(
            pady=20
        )

        tk.Label(
            window,
            text="Student ID"
        ).pack()

        student_id_entry = tk.Entry(
            window,
            font=("Segoe UI", 12),
            width=30
        )

        student_id_entry.pack(
            pady=5
        )

        tk.Label(
            window,
            text="Student Name"
        ).pack(
            pady=(10, 0)
        )

        name_entry = tk.Entry(
            window,
            font=("Segoe UI", 12),
            width=30
        )

        name_entry.pack(
            pady=5
        )

        def start_registration():

            student_id = (
                student_id_entry
                .get()
                .strip()
            )

            name = (
                name_entry
                .get()
                .strip()
            )

            if not student_id or not name:

                messagebox.showerror(
                    "Error",
                    "Please enter Student ID and Name."
                )

                return

            window.destroy()

            registration = StudentRegistration()

            success = registration.register_student(
                student_id,
                name
            )

            if success:

                messagebox.showinfo(
                    "Success",
                    f"{name} registered successfully!"
                )

                self.update_statistics()

        tk.Button(
            window,
            text="Start Camera Registration",
            command=start_registration,
            font=("Segoe UI", 11, "bold"),
            bg="#3498db",
            fg="white",
            padx=15,
            pady=8
        ).pack(
            pady=25
        )

    # ---------------- ATTENDANCE ----------------

    def start_attendance(self):

        attendance = AttendanceSystem()

        if len(attendance.students) == 0:

            messagebox.showwarning(
                "No Students",
                "Please register at least one student first."
            )

            return

        messagebox.showinfo(
            "Attendance",
            "Camera will start now.\n\n"
            "Look at the camera.\n"
            "Press ESC to stop."
        )

        attendance.start_attendance()

        self.update_statistics()

    # ---------------- VIEW ATTENDANCE ----------------

    def view_attendance(self):

        today = datetime.now().strftime(
            "%Y-%m-%d"
        )

        attendance_file = os.path.join(
            "attendance",
            f"attendance_{today}.csv"
        )

        if not os.path.exists(
            attendance_file
        ):

            messagebox.showinfo(
                "Attendance",
                "No attendance has been recorded today."
            )

            return

        window = tk.Toplevel(
            self.root
        )

        window.title(
            "Today's Attendance"
        )

        window.geometry(
            "750x450"
        )

        columns = (
            "Student ID",
            "Name",
            "Date",
            "Time",
            "Status"
        )

        tree = ttk.Treeview(
            window,
            columns=columns,
            show="headings"
        )

        for column in columns:

            tree.heading(
                column,
                text=column
            )

            tree.column(
                column,
                width=130
            )

        tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20
        )

        with open(
            attendance_file,
            "r",
            encoding="utf-8"
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                tree.insert(
                    "",
                    "end",
                    values=(
                        row["Student ID"],
                        row["Name"],
                        row["Date"],
                        row["Time"],
                        row["Status"]
                    )
                )

    # ---------------- STATISTICS ----------------

    def update_statistics(self):

        students_dir = os.path.join(
            "data",
            "students"
        )

        student_count = 0

        if os.path.exists(
            students_dir
        ):

            student_count = len(
                [
                    file
                    for file in os.listdir(
                        students_dir
                    )
                    if file.endswith(".npz")
                ]
            )

        today = datetime.now().strftime(
            "%Y-%m-%d"
        )

        attendance_file = os.path.join(
            "attendance",
            f"attendance_{today}.csv"
        )

        attendance_count = 0

        if os.path.exists(
            attendance_file
        ):

            with open(
                attendance_file,
                "r",
                encoding="utf-8"
            ) as file:

                attendance_count = max(
                    0,
                    sum(1 for _ in file) - 1
                )

        self.students_card.value_label.config(
            text=str(student_count)
        )

        self.attendance_card.value_label.config(
            text=str(attendance_count)
        )


    # ---------------- FOOTER ----------------

    def create_footer(self):

        footer = tk.Label(
            self.root,
            text="AttendAI • AI-Powered Attendance System",
            font=("Segoe UI", 9),
            bg="#f4f6f8",
            fg="#7f8c8d"
        )

        footer.pack(
            pady=10
        )


def main():

    root = tk.Tk()

    app = AttendAIGUI(
        root
    )

    root.mainloop()


if __name__ == "__main__":
    main()