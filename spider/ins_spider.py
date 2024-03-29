import requests
from bs4 import BeautifulSoup


def ins_download(url):
    print('ins_url' + url)
    # 发送GET请求
    response = requests.get(url)

    # 解析HTML内容
    soup = BeautifulSoup(response.text, 'html.parser')

    # 找到所有图片标签
    images = soup.find_all('img')

    # 提取图片URL并下载
    for image, index in enumerate(images):
        # 获取图片的URL
        img_url = image['src']

        # 下载并保存图片
        img_name = f'image_{index}.jpg'
        img_data = requests.get(img_url).content
        with open('image_name.jpg', 'wb') as handler:
            handler.write(img_data)


# 用你的Instagram URL替换
url = 'https://www.instagram.com/p/C46unTmLF1Z/?igsh=MTk5eGx0Z2VzYmNrZA=='
