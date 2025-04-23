#!/usr/bin/env python3
import base64
import sys


def decode_base64_file(file_path):
    """
    读取文件内容并进行Base64解码

    :param file_path: 要解码的文件路径
    :return: 解码后的字符串
    """
    try:
        with open(file_path, 'rb') as file:
            encoded_content = file.read()
            # 移除可能的空白字符
            encoded_content = encoded_content.strip()
            # 进行Base64解码
            decoded_content = base64.b64decode(encoded_content)
            return decoded_content.decode('utf-8')
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
        sys.exit(1)
    except Exception as e:
        print(f"解码时发生错误: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    # if len(sys.argv) != 2:
    #     print("使用方法: python base64_decoder.py <文件路径>")
    #     sys.exit(1)
    #
    # file_path = sys.argv[1]
    decoded = decode_base64_file("D:\\files\\服务器数据\\config.json")
    print("解码结果:")
    print(decoded)
