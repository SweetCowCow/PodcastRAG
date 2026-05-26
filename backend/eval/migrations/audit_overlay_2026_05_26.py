"""Overlay 7 試水 audited items (b22 / b27 / b29 / b11 / b15 / b14 / mt01) onto a
v2-migrated dataset, replacing the auto-migrated 'PENDING AUDIT' entries with the
human-verified entries from docs/case-studies/chat-rag-dataset-audit-2026-05-25.md.

Run after v1_to_v2_schema.py. Idempotent (safe to re-run).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OVERLAYS = {
    "b22": {
        "id": "b22",
        "design_type": "cross_episode",
        "source": "existing:q06-hosts-evolution-cross-episode-rewrite",
        "is_multi_turn": False,
        "question": "《這又沒有很屌》除了來賓以外，還有哪些人經常參與節目？",
        "expected_behavior": "answer",
        "expected_answer_summary": "除了主持人迪拉外，杜宗祐、方品融、阿名是節目的固定參與者（非來賓）。可從多集對話中觀察到他們穩定參與輪流播歌、主持對話的模式。",
        "expected_answer_aliases": {
            "杜宗祐": ["杜忠祐"],
            "阿名": ["阿鳴"],
            "方品融": ["方品龍"],
        },
        "expected_tool_calls_required": ["search_across_episodes"],
        "expected_tool_calls_acceptable": ["get_show_overview", "list_episodes"],
        "expected_tool_args": None,
        "expected_episode_uuids_must": None,
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": None,
        "expected_episode_numbers_acceptable": None,
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": None,
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_must_contradict_check": None,
        "audit_status": "human-verified-2026-05-25",
        "audit_notes": "原題『主持陣容變化』因 ASR 錯字 + 時序事件 audit 成本高，簡化為『識別固定參與者』。Transcript 內有明確證據。Agent 必須走 search_across_episodes 才能答，壓力測試 search 路徑。",
    },
    "b27": {
        "id": "b27",
        "design_type": "negative",
        "source": "existing:q02-no-rap-championship",
        "is_multi_turn": False,
        "question": "迪拉胖在 EP1 有提到自己得過什麼嘻哈大賽冠軍嗎？",
        "expected_behavior": "refusal_with_correction",
        "expected_answer_summary": "EP1 中迪拉胖沒有提到自己得過嘻哈大賽冠軍。他在節目中提及的嘻哈相關身份是「大嘻哈評審」（不是參賽得獎者），另一個身份是顏社（廠牌）老闆。Agent 應拒答『冠軍』前提錯誤的問題，並可補充正確身份。",
        "expected_answer_aliases": {"顏社": ["顏色"]},
        "expected_tool_calls_required": ["find_episode_by_ref", "search_within_episode"],
        "expected_tool_calls_acceptable": ["get_episode_segments"],
        "expected_tool_args": {"find_episode_by_ref": {"ref_must_match_pattern": "^EP1$|^第1集$"}},
        "expected_episode_uuids_must": ["9359c207-1970-4ab4-acce-bf8d44967b68"],
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": [1],
        "expected_episode_numbers_acceptable": None,
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": None,
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_must_contradict_check": None,
        "audit_status": "human-verified-2026-05-25",
        "audit_notes": "Negative trap clean pass。Agent refuse + 補大嘻哈評審身份。SQL bug fix 是這題能跑通的前提。新增 alias「顏社」← 顏色 typo。",
    },
    "b29": {
        "id": "b29",
        "design_type": "leading_question_yes",
        "source": "existing:q10-anchored-belonging-cross",
        "is_multi_turn": False,
        "question": "迪拉在《這又沒有很屌》裡有講過『安身之處』或『被照顧到』這個概念嗎？",
        "expected_behavior": "answer",
        "expected_answer_summary": "YES — 迪拉在多集中討論過「安身之處」與「被照顧」的概念。EP134（馬力全開的開工歌單）最完整：精神 / 物理上的安身之處（家、朋友、平靜）+ 推薦《Is there a place for you there》；EP143 有「家常味」與對「家」的想像；EP41 提到家庭照顧歷程。Agent 不應被『有講過…嗎』的疑問語氣誘導 refuse。",
        "expected_answer_aliases": None,
        "expected_tool_calls_required": ["search_across_episodes"],
        "expected_tool_calls_acceptable": ["find_episodes_by_topic"],
        "expected_tool_args": None,
        "expected_episode_uuids_must": ["c1d87278-7dba-4fb1-930d-c2bd3a3461d2"],
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": [134],
        "expected_episode_numbers_acceptable": [41, 143],
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": None,
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_must_contradict_check": None,
        "audit_status": "human-verified-2026-05-26",
        "audit_notes": "原 dataset design_type/review_notes 與 source_note 衝突；改 leading_question_yes（YES）。EP134 must、EP41+EP143 acceptable。EP143 retrieval miss 是已知 retrieval signal。",
    },
    "b11": {
        "id": "b11",
        "design_type": "date_find",
        "source": "new:N4",
        "is_multi_turn": False,
        "question": "2024 年上半年（1-6 月）發過哪幾集？",
        "expected_behavior": "answer",
        "expected_answer_summary": "2024 年 1-6 月共 26 集，含 EP25-EP47（23 集）+ 3 集龍年特別企劃（年菜改造 / 初二回娘家 / 開工歌單）。Agent 應呼叫 find_episodes_by_date(2024-01-01, 2024-06-30) 並如實回報 26 集，不該編造數字。",
        "expected_answer_aliases": None,
        "expected_tool_calls_required": ["find_episodes_by_date"],
        "expected_tool_calls_acceptable": [],
        "expected_tool_args": {
            "find_episodes_by_date": {
                "start": "2024-01-01",
                "end": "2024-06-30",
            }
        },
        "expected_episode_uuids_must": [
            "53d60c90-e783-4eff-969c-02feb6f82d0c",
            "79caf414-4d62-48a0-af91-5dffda70be8d",
            "d6398c78-5a60-4aab-a835-40803d3ac9e9",
            "dc1260c0-b95c-48f1-aa92-787696f64e91",
            "9c2a9529-81d2-4407-96bc-e566f333dcae",
            "b1d5ea60-f332-4159-96a0-91553bc674ed",
            "ecd66de6-cb4f-40e2-ba62-b07f2ff94e10",
            "89f0fab0-bca5-4695-b587-ac603db47cbe",
            "3dea68b0-bd9b-4b91-975e-fdc96f40c256",
            "ce0404c0-6c6f-4ca3-a7cd-e38f245f1ef0",
            "368e1aa0-0796-488c-a47c-b5b6769ad02a",
            "dcce2640-6ab8-4865-affd-41ace6c9ee6e",
            "2c0f87b6-1d10-40db-a202-3746e4dade6b",
            "780b332f-64bd-4e70-aa14-46f029be1528",
            "a2006c63-fd4e-42da-b0ba-c23531da6d6f",
            "5fb343b5-e459-48e8-bd3c-aed168f0bfa6",
            "b7661ca4-a9a0-4d74-b3a6-c114d2019b9b",
            "0431b7c8-ae3f-4cc5-bad6-2fd6c60a661f",
            "49d0852e-362e-4477-9f9a-3e917abe75f5",
            "e52f436d-33d7-4e10-a205-50f38535e28f",
            "3e77db47-86ac-4dbe-bfb5-b7f319364b82",
            "b46bedb7-2832-4024-936e-60349fa60c55",
            "65030207-726d-43ba-80d4-d4c0efb97ac8",
            "201bf4d9-0a5a-49cb-8d5b-875d8b78fa81",
            "8367adc5-0763-4b03-b072-adb2cbce5a46",
            "2ac5d7d5-5d24-4315-a6b0-071aea110fab",
        ],
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": None,
        "expected_episode_numbers_acceptable": None,
        "expected_count": 26,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": None,
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_must_contradict_check": None,
        "audit_status": "human-verified-2026-05-26",
        "audit_notes": "Date range retrieval 100% 正確。Prod 抓到 LLM number hallucination — tool 回 26 集，answer 文字寫 27。新增 count_consistency 指標偵測。",
    },
    "b15": {
        "id": "b15",
        "design_type": "deep_dive",
        "source": "existing:q11-ep19-guest-dad-rental-shop",
        "is_multi_turn": False,
        "question": "EP19《動漫歌單》來賓提到他爸爸以前在哪裡工作？後來兼差開了什麼店讓他接觸到漫畫？",
        "expected_behavior": "answer",
        "expected_answer_summary": "EP19 來賓提到爸爸以前在電信局（屬公務人員）工作，後來兼差開了一家錄影帶店，來賓在錄影帶店環境中接觸到漫畫。Agent 答出電信局＋錄影帶店＋接觸漫畫的因果鏈即視為正確；不必額外贅述「公務人員」字面。",
        "expected_answer_aliases": {"電信局": ["公務人員", "公家機關"]},
        "expected_tool_calls_required": ["find_episode_by_ref", "search_within_episode"],
        "expected_tool_calls_acceptable": ["get_episode_segments"],
        "expected_tool_args": {"find_episode_by_ref": {"ref_must_match_pattern": "^EP19$|^第19集$"}},
        "expected_episode_uuids_must": ["88f78fbe-d216-4334-bf4f-e3e3caeea48d"],
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": [19],
        "expected_episode_numbers_acceptable": None,
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": ["ep:88f78fbe-d216-4334-bf4f-e3e3caeea48d@1446.34"],
        "ground_truth_chunk_ids_either": None,
        "ground_truth_chunk_ids_acceptable": None,
        "expected_must_contradict_check": None,
        "audit_status": "human-verified-2026-05-26",
        "audit_notes": "Clean pass + Recall@5=1.0 + GT chunk 在 citations[2]。「公務人員」是電信局的同義 false-negative，新 schema 改用 alias 容錯。",
    },
    "b14": {
        "id": "b14",
        "design_type": "deep_dive",
        "source": "existing:q03-ep134-opening-song",
        "is_multi_turn": False,
        "question": "迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？他選的歌想表達什麼概念？",
        "expected_behavior": "answer",
        "expected_answer_summary": "EP134 迪拉胖（已 45 歲，過完農曆年的心境）刻意不挑振奮的開工歌，反而推薦版本盛泰郎（坂本龍一相關，2024 年初新專輯《YOHO》）的《Is there a place for you there》。歌曲傳達『世界一直在運轉、被迫做選擇，但要找到自己的安身之處』的概念，呼應中老年心境對安頓 / 平靜的需求，而非青壯年的衝刺感。Agent 必須抓到『故意不選振奮歌』的反差意圖，不能說『他推薦振奮人心的歌』。",
        "expected_answer_aliases": {
            "版本盛泰郎": ["版本聖太郎", "坂本龍一"],
            "YOHO": ["YOHO 專輯", "Is there a place for you there"],
        },
        "expected_tool_calls_required": ["find_episode_by_ref", "search_within_episode"],
        "expected_tool_calls_acceptable": ["get_episode_segments"],
        "expected_tool_args": {"find_episode_by_ref": {"ref_must_match_pattern": "^EP134$|^第134集$"}},
        "expected_episode_uuids_must": ["c1d87278-7dba-4fb1-930d-c2bd3a3461d2"],
        "expected_episode_uuids_acceptable": None,
        "expected_episode_numbers_must": [134],
        "expected_episode_numbers_acceptable": None,
        "expected_count": None,
        "expected_top_n_episode_numbers": None,
        "ground_truth_chunk_ids_must": ["ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@0.00"],
        "ground_truth_chunk_ids_either": [
            "ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@1790.18",
            "ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@1808.78",
        ],
        "ground_truth_chunk_ids_acceptable": ["ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@1663.58"],
        "expected_must_contradict_check": "answer 不得出現『推薦振奮歌 / 振奮人心』等敘述（與題目反問前提矛盾）",
        "audit_status": "human-verified-2026-05-26",
        "audit_notes": "(a) answer 自相矛盾被新 contradict_check 偵測；(b) retrieval 沒問題，agent search query 太抽象漏細節 chunk；(c) GT 漏標 @1663.58 + @1790.18/@1808.78 跨 boundary 重疊 → 三層分組 must / either / acceptable。",
    },
    "mt01": {
        "id": "mt01",
        "design_type": "multi_turn_ordinal",
        "source": "new:mt01-enumeration-carry",
        "is_multi_turn": True,
        "audit_status": "human-verified-2026-05-26",
        "audit_notes": "T1 retrieve OK；T2 LLM 不遵守 ORDINAL_INSTRUCTION，resolve 到 EP55 而非 EP131 — 已知 bug per agentic-severe-residual-fix-2026-05 archive，待 multi-turn-ordinal-mechanical-resolution propose 修。",
        "turns": [
            {
                "turn": "t1",
                "question": "歌單有哪幾集？",
                "expected_behavior": "answer",
                "expected_answer_summary": "節目共有 29 集屬「歌單」主題，最新三集（DESC）為 EP142、EP134、EP131。",
                "expected_answer_aliases": None,
                "expected_tool_calls_required": ["find_episodes_by_topic"],
                "expected_tool_calls_acceptable": [],
                "expected_tool_args": {"find_episodes_by_topic": {"topic": "歌單"}},
                "expected_episode_uuids_must": None,
                "expected_episode_uuids_acceptable": None,
                "expected_episode_numbers_must": None,
                "expected_episode_numbers_acceptable": None,
                "expected_count": 29,
                "expected_top_n_episode_numbers": [142, 134, 131],
                "ground_truth_chunk_ids_must": None,
                "ground_truth_chunk_ids_either": None,
                "ground_truth_chunk_ids_acceptable": None,
                "expected_must_contradict_check": None,
            },
            {
                "turn": "t2",
                "question": "第三集是什麼內容？",
                "expected_behavior": "answer",
                "expected_answer_summary": "第三集（按 DESC 排序的 index[2]）= EP131「當年不聽這個很落伍！一起回到2016 歌單」，內容為 2016 年流行歌單回顧。",
                "expected_answer_aliases": None,
                "expected_tool_calls_required": ["get_episode_summary"],
                "expected_tool_calls_acceptable": ["find_episode_by_ref"],
                "expected_tool_args": {
                    "get_episode_summary": {"episode_id_must_equal": "c1d87278-7dba-4fb1-930d-c2bd3a3461d2"}
                },
                "expected_episode_uuids_must": ["c1d87278-7dba-4fb1-930d-c2bd3a3461d2"],
                "expected_episode_uuids_acceptable": None,
                "expected_episode_numbers_must": [131],
                "expected_episode_numbers_acceptable": None,
                "expected_count": None,
                "expected_top_n_episode_numbers": None,
                "ground_truth_chunk_ids_must": None,
                "ground_truth_chunk_ids_either": None,
                "ground_truth_chunk_ids_acceptable": None,
                "expected_must_contradict_check": None,
                "carry_from": "t1.enumeration_episodes[2] sorted by published_at DESC",
                "ordinal_resolution_check": True,
            },
        ],
    },
}


def apply_overlay(dataset: dict) -> tuple[dict, int]:
    out = dict(dataset)
    items = []
    overlaid = 0
    for it in dataset["items"]:
        if it["id"] in OVERLAYS:
            items.append(OVERLAYS[it["id"]])
            overlaid += 1
        else:
            items.append(it)
    out["items"] = items
    return out, overlaid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.output)
    data = json.loads(src.read_text(encoding="utf-8"))
    out, overlaid = apply_overlay(data)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if overlaid != len(OVERLAYS):
        print(
            f"[warn] only {overlaid}/{len(OVERLAYS)} overlays applied (some ids not in dataset)",
            file=sys.stderr,
        )
    print(f"✓ overlaid {overlaid} items → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
