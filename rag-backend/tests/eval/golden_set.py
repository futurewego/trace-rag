"""最小评估集：P2a 的质量闸门，同时作为 P5 Golden Set 的种子。

expected_filename/expected_page 指向应当被检索到的来源。
问题覆盖已提交的 fixtures（real_scanned.pdf 的验收关键词）与常见问法。
"""

GOLDEN: list[dict] = [
    {
        "question": "合同编号是多少？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "甲方是哪家公司？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {"question": "乙方是谁？", "expected_filename": "real_scanned.pdf", "expected_page": 1},
    {
        "question": "合同标的金额是多少？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "合同生效日期？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "星曜科技在合同中是什么角色？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "黄河智能装备厂出现在哪份文件？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "HT-2026-0087 对应什么？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "人民币壹佰贰拾伍万元是什么金额？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "这份扫描件的主要内容是什么？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "合同双方各是谁？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
    {
        "question": "文件里提到的日期有哪些？",
        "expected_filename": "real_scanned.pdf",
        "expected_page": 1,
    },
]
