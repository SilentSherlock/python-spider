import random

activities = [
    ["电影", ["观看《肖申克的救赎》", "观看《阿甘正传》", "观看《盗梦空间》", "观看《星际穿越》", "观看《指环王》"]],
    ["学习", ["学习Python编程", "学习西班牙语", "参加在线数据科学课程", "学习绘画", "学习摄影技巧"]],
    ["旅行", ["探索巴黎", "参观长城", "徒步黄山", "游览京都", "参观大峡谷"]],
    ["烹饪", ["尝试制作意大利面", "烘焙巧克力蛋糕", "学习制作寿司", "制作泰式咖喱", "烤制披萨"]],
    ["运动", ["跑步5公里", "参加瑜伽课程", "打羽毛球", "游泳", "骑自行车"]],
    ["阅读", ["阅读《百年孤独》", "阅读《1984》", "阅读《哈利·波特》", "阅读《小王子》", "阅读《追风筝的人》"]],
    ["音乐", ["学习弹吉他", "听贝多芬的交响曲", "参加音乐会", "学习钢琴", "听爵士音乐"]],
    ["艺术", ["参观美术馆", "绘画一幅风景画", "学习雕塑", "制作陶艺", "学习书法"]],
    ["游戏", ["玩《塞尔达传说》", "玩《巫师3》", "玩《我的世界》", "玩《英雄联盟》", "玩《动物之森》"]],
    ["志愿服务", ["参加社区清洁活动", "帮助动物收容所", "参与老年人陪伴计划", "参加环保活动", "志愿教学"]],
    ["园艺", ["种植多肉植物", "修剪花园", "学习盆景艺术", "种植蔬菜", "设计花坛"]],
    ["手工艺", ["制作手工皂", "编织围巾", "制作陶艺", "制作手工卡片", "学习刺绣"]],
    ["摄影", ["拍摄城市风景", "拍摄自然风光", "学习人像摄影", "拍摄夜景", "制作摄影集"]],
    ["科技", ["组装一台电脑", "学习3D打印", "编写一个小程序", "学习机器人编程", "参加黑客马拉松"]],
    ["冥想", ["进行冥想练习", "练习深呼吸", "参加冥想工作坊", "学习瑜伽冥想", "进行正念练习"]]
]

random_topic = random.choice(activities)
random_activity = random.choice(random_topic[1])
print(f"本周的随机主题是：{random_topic[0]}")
print(f"具体活动是：{random_activity}")