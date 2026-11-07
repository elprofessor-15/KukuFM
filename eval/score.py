from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promofinder.validate import overlap_iou


def main() -> None:
    labels_path = Path("eval/labels.csv")
    labels = list(csv.DictReader(labels_path.open(encoding="utf-8"))) if labels_path.exists() else []
    if len(labels) < 8:
        print(f"Labels pending: found {len(labels)} rows, need 8 before scoring.")
        return
    promos_path = Path("outputs/promos.json")
    promos = json.loads(promos_path.read_text(encoding="utf-8"))
    candidates_by_label = {}
    for at in (5, 10, 20):
        hits = 0
        for index, label in enumerate(labels, 1):
            candidates = [promo for promo in promos if promo["segments"][0]["episode"] == int(label["episode"])]
            target = (float(label["start"]), float(label["end"]))
            overlaps = [(overlap_iou(target, (promo["segments"][0]["start"],
                                               promo["segments"][0]["end"])), promo)
                        for promo in candidates]
            candidates_by_label[index] = (label, max(overlaps, key=lambda item: item[0], default=None))
            if any(score >= .5 for score, _ in overlaps[:at]):
                hits += 1
        print(f"Recall at {at}: {hits}/{len(labels)} = {hits / len(labels):.3f}")
    misses = [(index, label, nearest) for index, (label, nearest) in candidates_by_label.items()
              if nearest is None or nearest[0] < .5]
    print("Misses at 20:")
    for index, label, nearest in misses:
        if nearest is None:
            print(f'  label {index}, episode {label["episode"]}: no candidate')
        else:
            promo = nearest[1]
            segment = promo["segments"][0]
            print(f'  label {index}, episode {label["episode"]}, '
                  f'{label["start"]} to {label["end"]}: nearest {promo["id"]} '
                  f'({segment["in"]} to {segment["out"]}), IoU {nearest[0]:.3f}')


if __name__ == "__main__":
    main()
