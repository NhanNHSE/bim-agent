"""Pydantic v2 schemas and validation rules for architectural functional programs."""

from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _is_grid_multiple(val: float, step: float = 0.1, tol: float = 1e-6) -> bool:
    nearest = round(val / step) * step
    return abs(val - nearest) <= tol


class KindRule(BaseModel):
    label: str
    min_width_m: float
    min_area_m2: float
    max_aspect: float
    needs_daylight: bool
    outdoor: bool
    source: str
    needs_engineer_review: bool


class Lot(BaseModel):
    width_m: float = Field(gt=0, le=50)
    depth_m: float = Field(gt=0, le=100)
    front_setback_m: float = Field(default=0.0, ge=0)
    back_setback_m: float = Field(default=0.0, ge=0)


class StairSpec(BaseModel):
    width_m: float = Field(default=2.2, gt=0)
    length_m: float = Field(default=4.0, gt=0)


class RoomReq(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: str
    entrance: bool = False
    adjacent_to: list[str] = Field(default_factory=list)
    min_width_m: float | None = None
    min_area_m2: float | None = None
    max_aspect: float | None = None
    target_area_m2: float | None = None
    needs_daylight: bool | None = None


class FloorReq(BaseModel):
    name: str
    rooms: list[RoomReq] = Field(min_length=1)


class Program(BaseModel):
    typology: Literal["nha_pho"]
    name: str
    lot: Lot
    storey_height_m: float = 3.6
    stair: StairSpec | None = None
    min_shared_m: float = 1.2
    floors: list[FloorReq] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_and_fill_defaults(self) -> Program:
        from src.design_core.typologies import load_rules

        rules = load_rules(self.typology)

        for field_name, val in (
            ("lot.width_m", self.lot.width_m),
            ("lot.depth_m", self.lot.depth_m),
            ("lot.front_setback_m", self.lot.front_setback_m),
            ("lot.back_setback_m", self.lot.back_setback_m),
        ):
            if not _is_grid_multiple(val):
                raise ValueError(f"{field_name}={val} phải là bội số của 0.1 m")

        if self.stair is not None:
            for field_name, val in (
                ("stair.width_m", self.stair.width_m),
                ("stair.length_m", self.stair.length_m),
            ):
                if not _is_grid_multiple(val):
                    raise ValueError(f"{field_name}={val} phải là bội số của 0.1 m")

        if len(self.floors) >= 2 and self.stair is None:
            raise ValueError("Nhà từ 2 tầng trở lên bắt buộc phải có cầu thang (stair)")

        for floor_idx, floor in enumerate(self.floors):
            seen_ids: set[str] = set()
            for room in floor.rooms:
                if room.id == "stair":
                    raise ValueError(f"{floor.name}: id 'stair' dành riêng cho cầu thang")
                if room.id in seen_ids:
                    raise ValueError(f"{floor.name}: trùng id phòng '{room.id}'")
                seen_ids.add(room.id)

                if room.kind not in rules:
                    raise ValueError(f"{floor.name}/{room.id}: loại phòng '{room.kind}' không có trong luật")

                rule = rules[room.kind]
                if room.min_width_m is None:
                    room.min_width_m = rule.min_width_m
                if room.min_area_m2 is None:
                    room.min_area_m2 = rule.min_area_m2
                if room.max_aspect is None:
                    room.max_aspect = rule.max_aspect
                if room.needs_daylight is None:
                    room.needs_daylight = rule.needs_daylight
                if room.target_area_m2 is None:
                    room.target_area_m2 = room.min_area_m2

            entrances = [r.id for r in floor.rooms if r.entrance]
            if floor_idx == 0:
                if len(entrances) != 1:
                    raise ValueError(
                        f"{floor.name}: tầng đầu phải có đúng 1 phòng entrance=True (hiện có {len(entrances)})"
                    )
            elif entrances:
                raise ValueError(f"{floor.name}: tầng trên không được có phòng entrance=True ({entrances})")

            valid_nodes = set(seen_ids)
            if self.stair is not None:
                valid_nodes.add("stair")

            adj: dict[str, set[str]] = {node: set() for node in valid_nodes}
            for room in floor.rooms:
                for target in room.adjacent_to:
                    if target == room.id:
                        raise ValueError(f"{floor.name}/{room.id}: không được kề với chính nó")
                    if target not in valid_nodes:
                        raise ValueError(
                            f"{floor.name}/{room.id}: yêu cầu kề với '{target}' không tồn tại trên tầng này"
                        )
                    adj[room.id].add(target)
                    adj[target].add(room.id)

            start_node = floor.rooms[0].id
            visited: set[str] = {start_node}
            queue: deque[str] = deque([start_node])
            while queue:
                curr = queue.popleft()
                for nxt in adj[curr]:
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)

            if len(visited) != len(valid_nodes):
                missing = sorted(valid_nodes - visited)
                raise ValueError(f"{floor.name}: đồ thị kề nhau không liên thông (cô lập: {missing})")

        return self
