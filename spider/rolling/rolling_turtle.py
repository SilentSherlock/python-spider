import tkinter as tk
from tkinter import ttk, font
import turtle
import random
from PIL import Image, ImageTk, ImageSequence
import rolling_stone


class DiceRollerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dice Roller")

        # Create canvas for turtle
        self.canvas = tk.Canvas(root, width=400, height=400)
        self.canvas.grid(row=0, column=0, rowspan=5)

        # Create turtle screen
        self.screen = turtle.TurtleScreen(self.canvas)
        self.screen.bgcolor("white")

        # Create turtle for drawing
        self.t = turtle.RawTurtle(self.screen)
        self.t.shape("turtle")
        self.t.color()

        # Create gif resource
        image_src = Image.open("../../resource/image/diceRollingByFa.gif")
        self.frames = []
        for frame in ImageSequence.Iterator(image_src):
            self.frames.append(ImageTk.PhotoImage(frame))
        self.canvas_image = self.canvas.create_image(-200, -200, anchor=tk.NW, image=self.frames[0])
        self.canvas_image_flag = False

        # Create labels and text boxes
        self.topic_label = ttk.Label(root, text="Topic")
        self.topic_label.grid(row=0, column=1)
        self.topic_entry = ttk.Entry(root)
        self.topic_entry.grid(row=0, column=2)

        self.activity_label = ttk.Label(root, text="Activity")
        self.activity_label.grid(row=1, column=1)
        self.activity_entry = ttk.Entry(root)
        self.activity_entry.grid(row=1, column=2)

        # Create start and accept button, start for roll, accept for change image
        self.start_button = ttk.Button(root, text="Start Rolling", command=self.start_roll)
        self.start_button.grid(row=2, column=1, columnspan=2)
        self.accept_button = ttk.Button(root, text="Accept", command=self.accept_roll)
        self.accept_button.grid(row=3, column=1, columnspan=2)

        # Draw initial stick figure with dice
        self.draw_star_figure()

    def draw_star_figure(self, text="Rolling Life Style"):
        # 使用font.Font只能加载系统字体，无法加载给定字体
        font_path = "../../resource/font/Caveat-VariableFont_wght.ttf"
        custom_font = font.Font(font="Consolas", size=20)
        self.canvas.create_text(-100, 100, anchor=tk.NW, text=text, font=custom_font)
        # print(font.families())

    def start_roll(self):
        self.t.clear()
        self.canvas_image_flag = True
        self.load_image()
        for _ in range(10):
            self.screen.update()
            self.screen.ontimer(lambda: None, 100)
        self.topic_entry.delete(0, tk.END)
        self.activity_entry.delete(0, tk.END)
        self.topic_entry.insert(0, "fuck")
        self.activity_entry.insert(0, "shit")
        self.canvas_image_flag = False

    def accept_roll(self):
        image_accept = Image.open("../../resource/image/clapFa.gif_s200x0")
        image_accept_frames = []
        for frame in ImageSequence.Iterator(image_accept):
            image_accept_frames.append(ImageTk.PhotoImage(frame))
        self.frames = image_accept_frames

    def load_image(self, frame_index=0):
        if self.canvas_image_flag:
            self.canvas.itemconfig(self.canvas_image, image=self.frames[frame_index])
            self.root.after(100, self.load_image, (frame_index + 1) % len(self.frames))


def main():
    root = tk.Tk()
    app = DiceRollerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
