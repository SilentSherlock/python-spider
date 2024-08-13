import tkinter as tk
import random

# 创建主窗口
root = tk.Tk()
root.title("掷骰子游戏")
root.geometry("600x400")

# 创建画布
canvas = tk.Canvas(root, width=600, height=400)
canvas.pack()


# 绘制线条小人
def draw_person(x, y):
    canvas.create_oval(x - 10, y - 10, x + 10, y + 10, fill="black")  # 头
    canvas.create_line(x, y + 10, x, y + 50)  # 身体
    canvas.create_line(x, y + 20, x - 20, y + 40)  # 左臂
    canvas.create_line(x, y + 20, x + 20, y + 40)  # 右臂
    canvas.create_line(x, y + 50, x - 20, y + 80)  # 左腿
    canvas.create_line(x, y + 50, x + 20, y + 80)  # 右腿


# 绘制骰子
def draw_dice(x, y, number):
    canvas.create_rectangle(x - 20, y - 20, x + 20, y + 20, fill="white")
    if number == 1:
        canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="black")
    elif number == 2:
        canvas.create_oval(x - 15, y - 15, x - 5, y - 5, fill="black")
        canvas.create_oval(x + 5, y + 5, x + 15, y + 15, fill="black")
    elif number == 3:
        canvas.create_oval(x - 15, y - 15, x - 5, y - 5, fill="black")
        canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="black")
        canvas.create_oval(x + 5, y + 5, x + 15, y + 15, fill="black")
    elif number == 4:
        canvas.create_oval(x - 15, y - 15, x - 5, y - 5, fill="black")
        canvas.create_oval(x + 5, y - 15, x + 15, y - 5, fill="black")
        canvas.create_oval(x - 15, y + 5, x - 5, y + 15, fill="black")
        canvas.create_oval(x + 5, y + 5, x + 15, y + 15, fill="black")
    elif number == 5:
        canvas.create_oval(x - 15, y - 15, x - 5, y - 5, fill="black")
        canvas.create_oval(x + 5, y - 15, x + 15, y - 5, fill="black")
        canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="black")
        canvas.create_oval(x - 15, y + 5, x - 5, y + 15, fill="black")
        canvas.create_oval(x + 5, y + 5, x + 15, y + 15, fill="black")
    elif number == 6:
        canvas.create_oval(x - 15, y - 15, x - 5, y - 5, fill="black")
        canvas.create_oval(x + 5, y - 15, x + 15, y - 5, fill="black")
        canvas.create_oval(x - 15, y - 5, x - 5, y + 5, fill="black")
        canvas.create_oval(x + 5, y - 5, x + 15, y + 5, fill="black")
        canvas.create_oval(x - 15, y + 5, x - 5, y + 15, fill="black")
        canvas.create_oval(x + 5, y + 5, x + 15, y + 15, fill="black")


# 掷骰子动画
def roll_dice():
    canvas.delete("all")
    draw_person(300, 100)
    for _ in range(10):  # 模拟骰子滚动动画
        dice_num = random.randint(1, 6)
        draw_dice(300, 200, dice_num)
        root.update()
        root.after(100)
    # 最终结果
    result = random.randint(1, 6)
    draw_dice(300, 200, result)


# 创建按钮
button = tk.Button(root, text="开始", command=roll_dice)
canvas.create_window(300, 350, window=button)

# 运行主循环
root.mainloop()
