def calculate_additional_amount():
    try:
        # 用户输入部分
        current_qty = float(input("请输入当前持有数量："))
        current_cost_price = float(input("请输入当前成本单价："))
        current_price = float(input("请输入当前标的市场价格："))
        target_cost_price = float(input("请输入目标平均成本价："))

        # 计算当前总成本
        current_total_cost = current_qty * current_cost_price

        # 设置未知数 x = 需要再买多少个
        # 解方程：(当前总成本 + x × 当前价格) / (当前数量 + x) = 目标成本价
        # 推导出：x = (当前总成本 - 当前数量 × 目标成本价) / (目标成本价 - 当前价格)
        numerator = current_total_cost - current_qty * target_cost_price
        denominator = target_cost_price - current_price

        if denominator == 0:
            print("当前价格与目标价格相同，无法通过加仓改变成本。")
            return

        x = numerator / denominator

        if x <= 0:
            print("目标成本价已达成或当前价格高于目标价，无需加仓。")
            return

        additional_cost = x * current_price

        print(f"\n你需要再买入约 {x:.4f} 个")
        print(f"预计花费：{additional_cost:.2f} 元")
        print(f"加仓后总持仓为：{current_qty + x:.4f} 个，平均成本约为：{target_cost_price:.2f} 元")

    except ValueError:
        print("输入格式有误，请确保输入的是数字。")


if __name__ == "__main__":
    calculate_additional_amount()
