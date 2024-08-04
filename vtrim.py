#!/usr/bin/env python3

import getopt
import sys
import re

from datetime import datetime
import signal
import shutil
import os
import logging
import subprocess
import enum
import jsonpickle
import math
import cv2

logLevel = logging.INFO
# logLevel = logging.DEBUG

Operations = enum.Enum('Operations', ('CutVideoFile',
                       'BuildHashDB', 'AppendToHashDB', "Error"))


class Configs:
    __max_hamming_distance = 7

    def __init__(self):

        similarity = 0.8
        self.max_header_length_ms = 5 * 60 * 1000

        self.op = Operations.Error
        self.db = "clips.db"
        self.sources = ["in"]
        self.dest = "out"
        self.move_file_after_cut = False
        self.log_file_name = None

        self.exts = None
        self.end = -1
        self.__max_hamming_distance = math.ceil(8 * 4 * (1-similarity))
        self.debug("current directory:", os.getcwd())

        self.__closed = False
        signal.signal(signal.SIGINT, self.__handle_ctrl_c)

    def __handle_ctrl_c(self, _, __):
        self.info('detect Ctrl+C signal.')
        self.info("await pending jobs to finish...")
        self.__closed = True

    def isCancelled(self):
        return self.__closed

    def isSimilar(self, hashes, hash):
        if hash in hashes:
            self.debug("hit hash:", hash)
            return True

        for h in hashes:
            diff = hamming(h, hash)
            if diff < self.__max_hamming_distance:
                self.debug("similar to:", h, "diff:", diff)
                return True

        self.debug("new hash:", hash)
        return False

    def writeToLogFile(self, line):
        if self.log_file_name != None:
            with open(self.log_file_name, "a+") as f:
                f.write(line)
                f.write("\n")

    def __log(self, level, argv):
        if level < logLevel:
            return

        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")
        l = logging.getLevelName(level)
        msg = ' '.join(map(str, argv))
        line = f"{t} [{l}] {msg}"
        print(line)
        if self.log_file_name != None:
            with open(self.log_file_name, "a+") as f:
                f.write(line)
                f.write("\n")

    def debug(self, *argv):
        self.__log(logging.DEBUG, argv)

    def info(self, *argv):
        self.__log(logging.INFO, argv)

    def error(self, *argv):
        self.__log(logging.ERROR, argv)

    def clearHashDB(self):
        with open(self.db, "w"):
            pass

    def appendHashDB(self, hash):
        with open(self.db, "a+") as f:
            f.write(str(hash))
            f.write("\n")

    def hasValidExtension(self, path):
        if self.exts == None:
            return True
        lower = path.lower()
        for ext in self.exts:
            if lower.endswith(ext):
                return True
        return False


def doCutVideoFiles(cfg: Configs):
    cfg.debug("cut video with configs:")
    cfg.debug(jsonpickle.encode(cfg))

    if not os.path.isfile(cfg.db):
        cfg.error("db file", f"\"{cfg.db}\"", "not found")
        return 1

    hashes = loadHashDB(cfg)
    success, fail = 0, 0
    for source in cfg.sources:
        if cfg.isCancelled():
            break
        for src in getAllVideoFiles(cfg, source):
            if cfg.isCancelled():
                break
            if processVideoFile(cfg, hashes, src):
                success += 1
            else:
                fail += 1
    cfg.info("total:", success + fail, "success:", success, "skip:", fail)
    return 0


def findCutPoint(cfg: Configs, heashes, src):
    video = cv2.VideoCapture(src)
    # fps = math.floor(video.get(cv2.CAP_PROP_FPS))
    count, ms, t = 0, 0, 1000
    while video.isOpened():
        if cfg.isCancelled():
            ms = -1
            break
        ok, image = video.read()
        ms = math.floor(video.get(cv2.CAP_PROP_POS_MSEC))
        if not ok or ms > cfg.max_header_length_ms:
            break
        count += 1
        cfg.debug("reading frame:", count, "at:", ms, "ms")
        if ms >= t:
            t += 1000
            cfg.debug("matching frame:", count, "at:", ms, "ms")
            hash = pHash(image)
            if not cfg.isSimilar(heashes, hash):
                break
    video.release()
    return ms


def cutOneVideoFile(cfg: Configs, src: str, ms: int):
    filename = os.path.basename(src)
    dest = os.path.abspath(os.path.join(cfg.dest, filename))

    sec = ms / 1000
    cfg.info("cut at:", sec, "seconds")
    # ffmpeg -i input.mp4 -ss 00:05:20 -t 00:10:00 -c:v copy -c:a copy output1.mp4
    cmd = ["ffmpeg", "-i", src, "-c:v", "copy",
           "-c:a", "copy", "-ss", str(sec), "-y", dest]
    cfg.debug("exec:", *cmd)
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

    if r.returncode != 0:
        cfg.error("result: failed")
        return

    if cfg.move_file_after_cut:
        cfg.info("move:", dest)
        cfg.info("to:", src)
        shutil.move(dest, src)
    cfg.info("result: success")
    return True


def processVideoFile(cfg: Configs, hashes, src):
    if not os.path.isfile(src):
        cfg.info("not a file:", src)
        return
    cfg.info("analyzing file:", src)
    try:
        end = findCutPoint(cfg, hashes, src)
        if end > 3000:
            return cutOneVideoFile(cfg, src, end)
        else:
            cfg.info("pass")
    except Exception as err:
        cfg.error(f"Unexpected {type(err)=}, {err=}")
    return False


def loadHashDB(cfg):
    db = cfg.db
    r = set()
    if not os.path.isfile(db):
        return r
    cfg.info("loading hash DB:", db)
    with open(cfg.db, "r") as f:
        for line in f.readlines():
            r.add(int(line))
    cfg.info(len(r), "hashes loaded")
    return r


def appendSampleVideoToHashDB(cfg, db, src, max):
    if not os.path.isfile(src):
        cfg.info("skip:", src)
        return

    cfg.info("analyzing file:", src)
    count, n = 0, 0
    video = cv2.VideoCapture(src)
    while video.isOpened():
        count += 1
        ok, image = video.read()
        ms = math.floor(video.get(cv2.CAP_PROP_POS_MSEC))
        if (not ok) or (max > 0 and ms > max):
            break
        hash = pHash(image)
        if hash not in db:
            n += 1
            cfg.info("DB size:", len(db) + 1, "frame:", count,
                     "hash:", hash, "at:", ms, "ms")
        db.add(hash)
    video.release()
    cfg.info("add", n, "new hashes")


def getAllVideoFiles(cfg: Configs, path):
    r = []
    if os.path.isfile(path):
        if cfg.hasValidExtension(path):
            r.append(path)
        return r

    for currentpath, folders, files in os.walk(path):
        for file in files:
            if cfg.hasValidExtension(file):
                fullpath = os.path.join(currentpath, file)
                r.append(fullpath)
    return r


def doAppendHash(cfg):
    cfg.debug("add hash to db with configs:")
    cfg.debug(jsonpickle.encode(cfg))

    if cfg.op == Operations.AppendToHashDB and cfg.end < 1:
        cfg.error("-t must bigger than zero")
        return 1

    max = cfg.end * 1000
    if cfg.op != Operations.AppendToHashDB:
        max = -1

    db = loadHashDB(cfg)
    n = len(db)
    for source in cfg.sources:
        for src in getAllVideoFiles(cfg, source):
            appendSampleVideoToHashDB(cfg, db, src, max)
    cfg.info("total new hashes:", len(db) - n)
    writeHashDB(cfg, db)
    return 0


def writeHashDB(cfg, db):
    cfg.info("write", len(db), "hashes:", cfg.db)
    cfg.clearHashDB()
    for hash in db:
        cfg.appendHashDB(hash)


def hamming(a, b):
    return bin(a ^ b).count('1')


def pHash(cv_image):
    imgsm = cv2.resize(cv_image, (320, 320), interpolation=cv2.INTER_CUBIC)
    imgg = cv2.cvtColor(imgsm, cv2.COLOR_BGR2GRAY)
    hash = cv2.img_hash.pHash(imgg)  # 8-byte hash
    ph = int.from_bytes(hash.tobytes(), byteorder='big', signed=False)
    return ph


def main():
    configs = parseCmdOptions()
    if configs != None:
        configs.writeToLogFile("")
        match configs.op:
            case Operations.CutVideoFile:
                return doCutVideoFiles(configs)
            case Operations.BuildHashDB:
                return doAppendHash(configs)
            case Operations.AppendToHashDB:
                return doAppendHash(configs)
            case _:
                pass
    printUsageInfo()
    return 0


def printUsageInfo():
    print("Usage:")
    print("trimmer.py -a -d clips.db -i ./video.mp4 -t 30")
    print("trimmer.py -b -d clips.db -i ./samples")
    print("trimmer.py -c -m -d clips.db -i ./in -o ./out -e \"mp4 mkv avi\"")
    print("    -a --add     add to clips database")
    print("    -b --build   build clips database")
    print("    -c --cut     cut video")
    print("    -e --ext     video file extensions e.g \"mp4 mkv\"")
    print("    -m --move    move video back to source dir after cut")
    print("    -d --db      clips database filename")
    print("    -i --in      sources video file or dir")
    print("    -l --log     log file name")
    print("    -o --out     output dir")
    print("    -t --time    sampling time in seconds")


def parseCmdOptions():
    # Remove 1st argument from the
    # list of command line arguments
    args = sys.argv[1:]
    if len(args) < 1 or "-h" in args or "--help" in args:
        return None

    # Options
    options = "habcmd:e:l:i:o:t:"

    # Long options
    long_options = ["help", "build", "cut",
                    "add", "move", "db=", "in=", "out=", "time=", "log=", "ext="]

    configs = Configs()

    if "-i" in args or "--in" in args:
        configs.sources = []

    # Parsing argument
    opts, _ = getopt.getopt(args, options, long_options)

    # checking each argument
    for key, value in opts:
        # print("arg:", currentArgument, "val:", currentValue)s
        if key in ("-b", "--build"):
            configs.op = Operations.BuildHashDB
        elif key in ("-c", "--cut"):
            configs.op = Operations.CutVideoFile
        elif key in ("-a", "--add"):
            configs.op = Operations.AppendToHashDB
        elif key in ("-d", "--db"):
            configs.db = value
        elif key in ("-e", "--ext"):
            configs.exts = set(
                ["." + x for x in re.split(r' |,|\.', value.lower()) if x])
        elif key in ("-m", "--move"):
            configs.move_file_after_cut = True
        elif key in ("-l", "--log"):
            configs.log_file_name = value
        elif key in ("-i", "--in"):
            if not os.path.exists(value):
                configs.error("path not exists:", value)
                return None
            configs.sources.append(value)
        elif key in ("-o", "--out"):
            if not os.path.isdir(value):
                configs.error("dir not exists:", value)
                return None
            configs.dest = value
        elif key in ("-t", "--time"):
            configs.end = int(value)
        else:
            return None

    return configs


exit(main())
