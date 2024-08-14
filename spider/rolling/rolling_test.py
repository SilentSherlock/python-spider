import turtle
import math

# 创建屏幕
screen = turtle.Screen()

# 创建绿色小乌龟
green_turtle = turtle.Turtle()
green_turtle.color("green")
green_turtle.penup()
green_turtle.goto(0, -70)
green_turtle.pendown()

# 画波浪线长方形
length = 240
width = 120
wave_amplitude = 10
wave_frequency = 5

# 画长边的波浪线
for _ in range(2):
    for x in range(length):
        y = wave_amplitude * math.sin(x / wave_frequency)
        green_turtle.goto(green_turtle.xcor() + 1, green_turtle.ycor() + y)
    green_turtle.right(90)

    # 画宽边的波浪线
    for x in range(width):
        y = wave_amplitude * math.sin(x / wave_frequency)
        green_turtle.goto(green_turtle.xcor() + 1, green_turtle.ycor() + y)
    green_turtle.right(90)

# 完成绘图
turtle.done()
