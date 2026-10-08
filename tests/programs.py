"""Example programs used by the equivalence, golden and round-trip tests."""

from blockcode import build as b
from blockcode.examples import school  # noqa: F401  (re-exported for tests)


def pets():
    return {
        "not_equal_skips_empty": b.program(b.from_(
            "pets", b.where(b.cmp("!=", b.col("species"), b.lit("dog"))))),
        "not_skips_empty": b.program(b.from_(
            "pets", b.where(b.not_(b.cmp(">", b.col("age"), b.lit(3)))))),
        "is_empty": b.program(b.from_("pets", b.where(b.isempty(b.col("age"))))),
        "not_empty": b.program(b.from_("pets", b.where(b.not_(b.isempty(b.col("name")))))),
        "in_list": b.program(b.from_(
            "pets", b.where(b.inlist(b.col("species"), ["cat", "fish"])))),
        "or_with_empty": b.program(b.from_(
            "pets", b.where(b.or_(b.cmp(">", b.col("weight"), b.lit(10)),
                                  b.cmp("<", b.col("age"), b.lit(3)))))),
        "group_on_empty_key": b.program(b.from_(
            "pets", b.group(["owner"], b.agg("count", None, "n"), b.agg("count", "age", "aged"),
                            b.agg("avg", "weight", "avg_weight")))),
        "sort_with_empty": b.program(b.from_("pets", b.order("age", "pet_id"))),
        "sort_desc_with_empty": b.program(b.from_("pets", b.order(("weight", True)))),
        "left_join": b.program(b.from_("pets", b.join("owners", "owner", how="left"))),
        "inner_join": b.program(b.from_("pets", b.join("owners", "owner"),
                                        b.select("name", "city"))),
        "maths_with_empty": b.program(b.from_(
            "pets", b.derive("score", b.math("+", b.math("*", b.col("age"), b.lit(2)),
                                              b.col("weight"))))),
        "int_division": b.program(b.from_(
            "pets", b.derive("ratio", b.math("/", b.col("pet_id"), b.col("age"))))),
        "contains_empty": b.program(b.from_(
            "pets", b.where(b.not_(b.text("contains", b.col("name"), "o"))))),
    }
