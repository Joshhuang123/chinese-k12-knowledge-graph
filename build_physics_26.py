import json

entries = []

def k(name, why, unc=False):
    return {"name": name, "type": "knowledge", "why": why, "uncertain": unc}
def a(name, why, unc=False):
    return {"name": name, "type": "ability", "why": why, "uncertain": unc}
def m(name, why, unc=False):
    return {"name": name, "type": "method", "why": why, "uncertain": unc}

# physics-26 共 60 条
entries.append({"id":"physics_xzxbx3_rjb_exp16","prereq":[
    k("阿尔法粒子","实验使用阿尔法粒子作为入射粒子,没有此概念就读不出",False),
    k("原子","实验对象是金属箔中的原子,不知原子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl10","prereq":[
    m("统计推断","需要从大量散射数据推断内部结构的方法",False),
    m("反推","需要根据现象反推原因的推理方法",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt100","prereq":[
    k("光子能量","条件 hv 由光子能量决定,不知光子能量就读不出",False),
    k("能级","频率条件讨论不同能级间光子,不知能级就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt101","prereq":[
    k("原子","模型描述原子内部结构,不知原子就读不出",False),
    k("能量子","模型假设能级分立,需要能量子概念",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt102","prereq":[
    k("电子","电子云描述电子位置分布,不知电子就读不出",False),
    k("概率","电子云基于电子出现概率,不知概率就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt91","prereq":[
    k("光","光谱由光展开波长得到,不知光就读不出",False),
    k("波长","光谱是波长与强度分布,不知波长就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt92","prereq":[
    k("光谱","线状谱是光谱的一种,不知光谱就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt93","prereq":[
    k("光谱","连续谱是光谱的一种,不知光谱就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt94","prereq":[
    k("跃迁","特征谱线来自能级跃迁,不知跃迁就读不出",False),
    k("原子","特征谱线由不同原子的能级产生,不知原子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt95","prereq":[
    k("特征谱线","光谱分析利用特征谱线鉴别元素,不知概念就读不出",False),
    m("光谱分析","需要根据谱线位置比对元素的方法",True),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt96","prereq":[
    k("玻尔原子模型","公式由玻尔理论推导出,不知模型就读不出",False),
    k("能级","公式中包含不同能级,不知能级就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt97","prereq":[
    k("原子","定态是原子中电子的状态,不知原子就读不出",False),
    k("能量","定态是具有确定能量的状态,不知能量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt98","prereq":[
    k("定态","激发态与基态都是定态,不知定态就读不出",False),
    k("能量","激发态与基态按能量区分,不知能量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt99","prereq":[
    k("能级","跃迁发生在能级之间,不知能级就读不出",False),
    k("光子","跃迁伴随光子吸收或释放,不知光子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl11","prereq":[
    k("光谱分析","方法基于光谱分析鉴别元素,不知方法就读不出",False),
    k("特征谱线","需要掌握各元素特征谱线位置",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt103","prereq":[
    k("波粒二象性","假设把波动性扩展到实物粒子,不知二象性就读不出",False),
    k("光子","光子动量已具波动粒子双重性,不知光子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt104","prereq":[
    k("德布罗意假设","关系式是假设的数学表达,不知假设就读不出",False),
    k("光子","关系式中波长与光子动量形式相同,不知光子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt105","prereq":[
    k("波动性","物质波属于波动性范畴,不知波动就读不出",False),
    k("粒子","物质波与粒子相联系,不知粒子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt106","prereq":[
    k("波动性","衍射是波动性证据,不知波动就读不出",False),
    k("电子","衍射对象是电子,不知电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt107","prereq":[
    k("能量子","理论基于能量量子假设,不知能量子就读不出",False),
    k("玻尔原子模型","理论包括玻尔模型,不知模型就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt108","prereq":[
    k("量子化","力学基于物理量量子化,不知量子化就读不出",False),
    a("数学推理能力","需要能够处理矩阵代数的数学能力",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt109","prereq":[
    k("物质波","波动力学基于物质波概念,不知物质波就读不出",False),
    k("波动性","波动力学基于波动性,不知波动就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt110","prereq":[
    k("物质波","方程描述物质波行为,不知物质波就读不出",False),
    k("波动力学","方程是波动力学核心,不知力学就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt111","prereq":[
    k("矩阵力学","量子力学综合矩阵力学,不知矩阵力学就读不出",False),
    k("波动力学","量子力学综合波动力学,不知波动力学就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp17","prereq":[
    k("电子衍射","实验观察电子衍射,不知衍射就读不出",False),
    k("波动性","实验验证波动性,不知波动就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt112","prereq":[
    k("原子核","放射性来自原子核,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt113","prereq":[
    k("放射性","现象属于放射性表现,不知放射就读不出",False),
    k("原子核","现象由原子核自发产生,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt114","prereq":[
    k("阿尔法粒子","射线由阿尔法粒子组成,不知粒子就读不出",False),
    k("氦核","粒子实质是氦核,不知氦核就读不出本质",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt115","prereq":[
    k("电子","射线本质是电子流,不知电子就读不出",False),
    k("贝塔衰变","射线来自贝塔衰变,不知衰变就读不出来源",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt116","prereq":[
    k("电子","电离使电子脱离核束缚,不知电子就读不出",False),
    k("原子","电离作用发生在原子中,不知原子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt117","prereq":[
    k("电离作用","云室利用电离在离子附近形成雾滴,不知电离就读不出",False),
    k("粒子","云室显示带电粒子径迹,不知粒子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt118","prereq":[
    k("原子核","质子属于原子核组成,不知原子核就读不出",False),
    k("电荷量","质子具有正电荷量,不知电荷量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt119","prereq":[
    k("原子核","中子属于原子核组成,不知原子核就读不出",False),
    k("质量","中子具有质量,不知质量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt120","prereq":[
    k("质子","核子包括质子,不知质子就读不出组成",False),
    k("中子","核子包括中子,不知中子就读不出组成",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt121","prereq":[
    k("质子","电荷数等于质子数,不知质子就读不出",False),
    k("原子核","电荷数描述原子核的电荷量,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt122","prereq":[
    k("核子","质量数等于核子总数,不知核子就读不出",False),
    k("原子核","质量数描述原子核质量,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt123","prereq":[
    k("原子核","衰变是原子核的变化,不知原子核就读不出",False),
    k("放射性","衰变属于放射性过程,不知放射就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt124","prereq":[
    k("阿尔法粒子","衰变放出阿尔法粒子,不知粒子就读不出",False),
    k("原子核","衰变发生在原子核中,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt125","prereq":[
    k("中子","衰变涉及中子转变为质子,不知中子就读不出",False),
    k("电子","衰变放出电子,不知电子就读不出",False),
    k("原子核","衰变发生在原子核中,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt126","prereq":[
    k("质量数","守恒针对质量数,不知质量数就读不出",False),
    k("核反应","守恒是核反应中的规律,不知核反应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt127","prereq":[
    k("电荷数","守恒针对电荷数,不知电荷数就读不出",False),
    k("核反应","守恒是核反应中的规律,不知核反应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt128","prereq":[
    k("放射性衰变","半衰期描述衰变快慢,不知衰变就读不出",False),
    k("统计规律","半衰期是统计规律,不知统计就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt129","prereq":[
    k("原子核","反应发生在原子核,不知原子核就读不出",False),
    k("质量数守恒","反应服从质量数守恒,不知守恒就读不出",False),
    k("电荷数守恒","反应服从电荷数守恒,不知守恒就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt130","prereq":[
    k("放射性","同位素具有放射性,不知放射就读不出",False),
    k("同位素","同位素需先知概念,不知同位素就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt131","prereq":[
    k("放射性同位素","示踪使用放射性同位素,不知同位素就读不出",False),
    a("探测意识","需要识别可探测信号的方法意识",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt132","prereq":[
    k("电离作用","辐射通过电离损害人体,不知电离就读不出",False),
    a("安全防护意识","需要具备识别放射危险的日常意识",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl12","prereq":[
    k("质量数守恒","方法基于质量数守恒,不知守恒就读不出",False),
    k("电荷数守恒","方法基于电荷数守恒,不知守恒就读不出",False),
    k("核反应","方法用于书写核反应,不知核反应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt133","prereq":[
    k("引力","相互作用包括引力,不知引力就读不出",False),
    k("电场","电磁相互作用与电场相关,不知电场就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt134","prereq":[
    k("核子","相互作用发生在核子之间,不知核子就读不出",False),
    k("原子核","相互作用使核子结合成原子核,不知核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt135","prereq":[
    k("贝塔衰变","相互作用引起贝塔衰变,不知衰变就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt136","prereq":[
    k("原子核","结合能属于原子核的属性,不知核就读不出",False),
    k("能量","结合能是一种能量,不知能量就读不出",False),
    k("质量亏损","亏损量与结合能相对应,不知亏损就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt137","prereq":[
    k("结合能","比结合能基于结合能,不知结合能就读不出",False),
    k("核子","比值分子分母均涉及核子数,不知核子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt138","prereq":[
    k("原子核","质量亏损发生在原子核中,不知核就读不出",False),
    k("质能方程","亏损可由质能方程换算能量,不知方程就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt139","prereq":[
    k("能量","方程描述能量与质量,不知能量就读不出",False),
    k("质量","方程描述质量与能量,不知质量就读不出",False),
    k("光速","方程中含光速平方,不知光速就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt140","prereq":[
    k("原子核","裂变是原子核分裂,不知核就读不出",False),
    k("中子","裂变由中子轰击引发,不知中子就读不出",False),
    k("结合能","裂变释放结合能之差,不知结合能就读不出能量来源",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt141","prereq":[
    k("核裂变","临界质量针对裂变反应,不知裂变就读不出",False),
    k("中子","临界质量涉及中子产生与逃逸,不知中子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt142","prereq":[
    k("中子","慢化剂与中子碰撞减速,不知中子就读不出",False),
    k("核裂变","慢化剂用于裂变反应,不知裂变就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt143","prereq":[
    k("中子","控制棒吸收中子控制反应,不知中子就读不出",False),
    k("核裂变","控制棒用于裂变装置,不知裂变就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt144","prereq":[
    k("核裂变","电站利用核裂变释放能量,不知裂变就读不出",False),
    k("能量","电站将核能转为电能,不知能量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt145","prereq":[
    k("原子核","聚变发生在原子核之间,不知核就读不出",False),
    k("结合能","聚变释放结合能之差,不知结合能就读不出能量来源",False),
    k("高温","聚变需克服库仑斥力需要高温,不知高温就读不出条件",False),
],"dispute":[]})

assert len(entries)==60, len(entries)
with open('data/lmm-out/physics-26.json','w',encoding='utf-8') as f:
    json.dump(entries,f,ensure_ascii=False,indent=1)
print(f'Written physics-26: {len(entries)} entries')
total_pre = sum(len(e.get('prereq',[])) for e in entries)
print(f'Total prereqs: {total_pre}')