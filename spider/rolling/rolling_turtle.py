import tkinter as tk
from tkinter import ttk
import turtle
import random


class DiceRollerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dice Roller App")

        # Create canvas for turtle
        self.canvas = tk.Canvas(root, width=400, height=400)
        self.canvas.grid(row=0, column=0, rowspan=3)

        # Create turtle screen
        self.screen = turtle.TurtleScreen(self.canvas)
        self.screen.bgcolor("white")

        # Create turtle for drawing
        self.t = turtle.RawTurtle(self.screen)
        self.t.shape("turtle")
        self.t.hideturtle()

        # Create separator lines
        # self.canvas.create_line(160, 0, 160, 400, fill="gray", width=2)
        # self.canvas.create_line(0, 0, 240, 400, fill="gray", width=2)

        # Create labels and text boxes
        self.topic_label = ttk.Label(root, text="Topic")
        self.topic_label.grid(row=0, column=1)
        self.topic_entry = ttk.Entry(root)
        self.topic_entry.grid(row=0, column=2)

        self.activity_label = ttk.Label(root, text="Activity")
        self.activity_label.grid(row=1, column=1)
        self.activity_entry = ttk.Entry(root)
        self.activity_entry.grid(row=1, column=2)

        # Create start button
        self.start_button = ttk.Button(root, text="Start", command=self.start_roll)
        self.start_button.grid(row=2, column=1, columnspan=2)

        # Draw initial stick figure with dice
        self.draw_stick_figure()
        self.draw_dice(1)

    def draw_stick_figure(self):
        self.t.penup()
        self.t.goto(-100, 0)
        self.t.pendown()
        self.t.circle(20)  # Head
        self.t.penup()
        self.t.goto(-100, -20)
        self.t.pendown()
        self.t.goto(-100, -100)  # Body
        self.t.goto(-120, -140)  # Left leg
        self.t.penup()
        self.t.goto(-100, -100)
        self.t.pendown()
        self.t.goto(-80, -140)  # Right leg
        self.t.penup()
        self.t.goto(-100, -60)
        self.t.pendown()
        self.t.goto(-120, -40)  # Left arm
        self.t.penup()
        self.t.goto(-100, -60)
        self.t.pendown()
        self.t.goto(-80, -40)  # Right arm
        self.t.penup()
        self.t.goto(-100, 20)
        self.t.pendown()
        self.t.circle(5)  # Smile

    def draw_dice(self, number):
        self.t.penup()
        self.t.goto(-100, 40)
        self.t.pendown()
        self.t.write(f"Dice: {number}", align="center", font=("Arial", 16, "normal"))

    def start_roll(self):
        self.t.clear()
        self.draw_stick_figure()
        for _ in range(10):
            number = random.randint(1, 6)
            self.draw_dice(number)
            self.screen.update()
            self.screen.ontimer(lambda: None, 100)
        self.topic_entry.delete(0, tk.END)
        self.activity_entry.delete(0, tk.END)
        self.topic_entry.insert(0, f"Topic: {number}")
        self.activity_entry.insert(0, f"Activity: {number}")


def main():
    root = tk.Tk()
    app = DiceRollerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
