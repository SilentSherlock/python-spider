from spider import ins_spider


def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print_hi('PyCharm')
    print("ins download start")
    url = 'https://www.instagram.com/p/C46unTmLF1Z/?igsh=MTk5eGx0Z2VzYmNrZA=='
    ins_spider.ins_download(url)


# See PyCharm help at https://www.jetbrains.com/help/pycharm/
