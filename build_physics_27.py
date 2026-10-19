import json

entries = []

def k(name, why, unc=False):
    return {"name": name, "type": "knowledge", "why": why, "uncertain": unc}
def a(name, why, unc=False):
    return {"name": name, "type": "ability", "why": why, "uncertain": unc}
def m(name, why, unc=False):
    return {"name": name, "type": "method", "why": why, "uncertain": unc}

# physics-27 共 11 条
entries.append({"id":"physics_xzxbx3_rjb_cpt146","prereq":[
    k("磁场","方案依赖磁场对带电粒子的约束,不知磁场就读不出机理",False),
    k("洛伦兹力","磁场对粒子的作用靠洛伦兹力,不知洛伦兹力就读不出",False),
    k("热核反应","方案针对可控核聚变,不知聚变就读不出目标",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt147","prereq":[
    k("热核反应","方案针对核聚变,不知聚变就读不出目标",False),
    a("惯性直觉","需要理解物体因惯性维持运动的日常经验",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt148","prereq":[
    k("强子","分类包含强子,不知强子就读不出",False),
    k("轻子","分类包含轻子,不知轻子就读不出",False),
    k("规范玻色子","分类包含规范玻色子,不知规范玻色子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt149","prereq":[
    k("强相互作用","强子参与强相互作用,不知相互作用就读不出",False),
    k("质子","质子是强子之一,不知质子就读不出典型例子",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt150","prereq":[
    k("电子","电子是轻子典型成员,不知电子就读不出例子",False),
    k("电荷量","轻子性质涉及电荷量,不知电荷量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt151","prereq":[
    k("光子","光子是规范玻色子之一,不知光子就读不出",False),
    k("相互作用","规范玻色子传递相互作用,不知相互作用就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt152","prereq":[
    k("质量","粒子通过与希格斯场耦合获得质量,不知质量就读不出",False),
    k("量子化","希格斯玻色子是希格斯场的量子激发,不知量子化就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt153","prereq":[
    k("电荷量","反粒子电荷与正粒子相反,不知电荷就读不出区别",False),
    k("质量","反粒子质量与正粒子相同,不知质量就读不出共同属性",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt154","prereq":[
    k("强子","夸克构成强子,不知强子就读不出被组成关系",False),
    k("电荷量子化","夸克带分数电荷是量子化特殊情形,不知量子化就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt155","prereq":[
    k("夸克","禁闭描述夸克不可单独存在,不知夸克就读不出",False),
    k("强相互作用","禁闭由强相互作用导致,不知相互作用就读不出原因",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt156","prereq":[
    k("夸克","模型包括夸克,不知夸克就读不出",False),
    k("轻子","模型包括轻子,不知轻子就读不出",False),
    k("规范玻色子","模型包括规范玻色子,不知规范玻色子就读不出",False),
    k("希格斯玻色子","模型包括希格斯玻色子,不知希格斯玻色子就读不出",False),
],"dispute":[]})

assert len(entries)==11, len(entries)
with open('data/lmm-out/physics-27.json','w',encoding='utf-8') as f:
    json.dump(entries,f,ensure_ascii=False,indent=1)
print(f'Written physics-27: {len(entries)} entries')
total_pre = sum(len(e.get('prereq',[])) for e in entries)
print(f'Total prereqs: {total_pre}')