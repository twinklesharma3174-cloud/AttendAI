from src.student_registration import StudentRegistration
from src.attendance import AttendanceSystem


def register_student():

    print("\n" + "=" * 50)
    print("          STUDENT REGISTRATION")
    print("=" * 50)

    student_id = input("Enter Student ID: ").strip()
    name = input("Enter Student Name: ").strip()

    if not student_id or not name:
        print("Student ID and Name are required.")
        return

    registration = StudentRegistration()

    registration.register_student(
        student_id,
        name
    )


def start_attendance():

    print("\nStarting AttendAI Attendance System...")

    attendance = AttendanceSystem()

    if len(attendance.students) == 0:

        print("No students are registered yet.")
        return

    attendance.start_attendance()


def main():

    while True:

        print("\n")
        print("=" * 50)
        print("                 AttendAI")
        print("       Smart Attendance Management")
        print("=" * 50)

        print("\n1. Register Student")
        print("2. Start Attendance")
        print("3. Exit")

        choice = input("\nEnter your choice: ").strip()

        if choice == "1":

            register_student()

        elif choice == "2":

            start_attendance()

        elif choice == "3":

            print("\nThank you for using AttendAI.")
            break

        else:

            print("\nInvalid choice. Please try again.")


if __name__ == "__main__":
    main()