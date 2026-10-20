# 라벨링이 끝난 images/ labels/ 를 "영상 단위"로 train/val/test 로 나눈다.
import sys, random, re, shutil
from collections import defaultdict
from pathlib import Path

src = Path(sys.argv[1])   # labeled 폴더
dst = Path(sys.argv[2])   # 결과 폴더 (dataset)
random.seed(42)           # 매번 같은 결과가 나오게 고정

# 파일 이름에서 영상 이름만 떼어 묶는다 (Label Studio가 붙인 앞 8글자는 제거)
groups = defaultdict(list)
for img in sorted(p for p in (src / "images").glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"}):
    name = re.sub(r"^[0-9a-f]{8}-", "", img.stem)
    groups[name.rsplit("_", 1)[0]].append(img)

videos = list(groups)
random.shuffle(videos)
n = len(videos)
if n == 0:
    sys.exit(f"사진을 못 찾았어요: {src / 'images'} 폴더를 확인하세요")
split_of = {}
if n < 3:
    # 영상이 1~2개면 흐름 연습용으로 같은 사진을 train/val/test 모두에 넣는다
    print(f"[주의] 영상이 {n}개뿐이라 같은 사진을 train/val/test에 모두 넣어요. 점수는 의미 없고 흐름 연습용이에요")
    for v in videos:
        split_of[v] = ["train", "val", "test"]
else:
    n_val = max(1, round(n * 0.15))
    n_test = max(1, round(n * 0.15))
    for i, v in enumerate(videos):
        split_of[v] = ["val"] if i < n_val else ["test"] if i < n_val + n_test else ["train"]

count = defaultdict(int)
for v, imgs in groups.items():
    for s in split_of[v]:
        (dst / "images" / s).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / s).mkdir(parents=True, exist_ok=True)
        for img in imgs:
            shutil.copy(img, dst / "images" / s / img.name)
            lab = src / "labels" / (img.stem + ".txt")
            if lab.exists():
                shutil.copy(lab, dst / "labels" / s / lab.name)
            count[s] += 1

print(f"영상 {n}개 → train/val/test 사진 수: {count['train']} / {count['val']} / {count['test']}")
