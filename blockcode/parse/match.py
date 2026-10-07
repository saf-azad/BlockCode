"""Keep block ids stable when code is parsed back into blocks.

New blocks take the id of the previous block in the same place: same parent slot, same type,
same position among siblings of that type. Hover state, plot settings in the editor and
error links all survive a round trip through the code.
"""

from __future__ import annotations

from blockcode.ir import Block, Program


def keep_ids(new: Program, old: Program, spans: dict[str, list[int]]
             ) -> tuple[Program, dict[str, list[int]]]:
    rename: dict[str, str] = {}
    used: set[str] = set()

    def match_list(news: list[Block], olds: list[Block]) -> None:
        by_type: dict[str, list[Block]] = {}
        for o in olds:
            by_type.setdefault(o.type, []).append(o)
        seen: dict[str, int] = {}
        for n in news:
            k = seen.get(n.type, 0)
            seen[n.type] = k + 1
            pool = by_type.get(n.type, [])
            if k < len(pool):
                match_block(n, pool[k])

    def match_block(n: Block, o: Block) -> None:
        if o.id in used:
            return
        used.add(o.id)
        rename[n.id] = o.id
        for slot, child in n.inputs.items():
            oc = o.inputs.get(slot)
            if oc is not None and oc.type == child.type:
                match_block(child, oc)
        for name, stack in n.stacks.items():
            match_list(stack, o.stacks.get(name, []))

    match_list(new.blocks, old.blocks)

    def apply(b: Block) -> Block:
        return b.model_copy(update={
            "id": rename.get(b.id, b.id),
            "inputs": {k: apply(v) for k, v in b.inputs.items()},
            "stacks": {k: [apply(x) for x in v] for k, v in b.stacks.items()},
        })

    program = Program(blocks=[apply(b) for b in new.blocks])
    return program, {rename.get(k, k): v for k, v in spans.items()}
