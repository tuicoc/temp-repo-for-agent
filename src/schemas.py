"""Structured output schemas.

Following the pattern in the reference project: a Pydantic ``BaseModel`` per
shape, with a ``description`` on every field, handed to
``with_structured_output``.

The description is not documentation. It is part of the prompt — it is what
tells the model that ``ten_khach`` wants a bare given name and not "Chị Lan",
and that ``tong_tien_vnd`` is in đồng rather than in thousands. A bare JSON
schema with no descriptions was tried first and two of the four models got the
extraction wrong or returned nothing at all, because nothing told them what the
fields meant.

Passing the class rather than a plain dict also matters for portability.
LangChain picks the provider's native structured-output mode from the type it
is given; handed a raw dict it chose one NVIDIA rejects outright with
``unknown field guided_json``.

``config/probe_prompts.yaml`` refers to these by the names in :data:`SCHEMAS`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscountJudgement(BaseModel):
    """Verdict on a compound-discount claim."""

    khach_noi_dung: bool = Field(
        description=(
            "true nếu khách nói đúng, false nếu khách nói sai. "
            "Hai lần giảm liên tiếp không cộng dồn trực tiếp."
        )
    )
    muc_giam_thuc_te_phan_tram: float = Field(
        description=(
            "Tổng mức giảm thực tế so với giá gốc, tính bằng phần trăm. "
            "Chỉ điền con số, ví dụ 28 nghĩa là giảm 28%."
        )
    )
    giai_thich: str = Field(
        description="Giải thích ngắn gọn bằng tiếng Việt, tối đa 2 câu."
    )


class OrderExtraction(BaseModel):
    """Order details pulled out of one sentence of Vietnamese."""

    ten_khach: str = Field(
        description=(
            "Chỉ tên riêng của khách, không kèm xưng hô. "
            'Với "Chị Lan" thì điền "Lan".'
        )
    )
    thanh_pho: str = Field(description="Tên thành phố, viết có dấu tiếng Việt.")
    so_luong: int = Field(description="Số lượng sản phẩm khách đặt.")
    size: str = Field(description='Size sản phẩm, ví dụ "S", "M", "L".')
    mau: str = Field(description="Màu sản phẩm, viết bằng tiếng Việt.")
    tong_tien_vnd: int = Field(
        description=(
            "Tổng tiền quy về đơn vị đồng, không phải nghìn đồng. "
            '"350 nghìn" là 350000; "4 triệu 8" là 4800000.'
        )
    )


# Names that config/probe_prompts.yaml may refer to.
SCHEMAS: dict[str, type[BaseModel]] = {
    "DiscountJudgement": DiscountJudgement,
    "OrderExtraction": OrderExtraction,
}


def get_schema(name: str) -> type[BaseModel]:
    """Look up a schema class by the name used in the YAML."""
    try:
        return SCHEMAS[name]
    except KeyError:
        known = ", ".join(sorted(SCHEMAS))
        raise KeyError(f"Unknown schema {name!r}. Known: {known}") from None
