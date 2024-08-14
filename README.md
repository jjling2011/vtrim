vtrim.py 是一个用来删除视频片头的 python 脚本。

### 用法

```bash
# 安装需要的依赖，以 Archlinux 为例
sudo pacman -S python python-opencv python-jsonpickle ffmpeg

# 下载 vtrim.py 并添加可执行权限（略）

# 学习视频前 10 秒片头，存入 clips.db 中
# 每个参数的详细用法见 ./vtrim.py --help
./vtrim.py --add --db clips.db --in sample.mkv --time 10

# 创建文件夹用于存放裁剪后的视频
mkdir out/

# 根据学习到的 clips.db 裁剪视频
# 其中 --in 参数可以指定多次，或者指定一个文件夹
./vtrim.py --cut --db clips.db --in sample.mkv --out out/
```

### 进阶用法
使用环境变量可以少输些参数，详见 [vtrim.sh](./vtrim.sh)
