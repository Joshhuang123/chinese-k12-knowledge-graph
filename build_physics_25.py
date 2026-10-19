import json

entries = []

def k(name, why, unc=False):
    return {"name": name, "type": "knowledge", "why": why, "uncertain": unc}
def a(name, why, unc=False):
    return {"name": name, "type": "ability", "why": why, "uncertain": unc}
def m(name, why, unc=False):
    return {"name": name, "type": "method", "why": why, "uncertain": unc}

# physics-25 共 60 条

entries.append({"id":"physics_xzxbx3_rjb_cpt44","prereq":[
    k("分子间作用力","分子间引力造就表面张力，没有分子作用力就读不出来源",False),
    a("液体表面观察","需要直观感受液体表面有收缩趋势的生活经验",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt45","prereq":[
    k("分子间作用力","浸润源于分子作用力类型差异，没有分子作用力就读不出机理",False),
    a("固体表面观察","需要观察过水在玻璃上铺开的现象",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt46","prereq":[
    k("分子间作用力","不浸润源于同类分子引力大于异类分子，没有分子作用力就读不出",False),
    a("固体表面观察","需要观察过水银在玻璃上缩成球的现象",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt47","prereq":[
    k("浸润","毛细现象中浸润液体上升，没有浸润概念就读不出方向",False),
    k("不浸润","毛细现象中不浸润液体下降，没有不浸润就读不出方向",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt48","prereq":[
    k("晶体","液晶分子排列有序性与晶体相似，没有晶体概念就读不出有序性",False),
    k("液体","液晶具有流动性，没有液体概念就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp7","prereq":[
    k("液体的表面张力","实验直接展示表面张力效应，没有概念就读不出",False),
    a("细线弯曲观察","需要观察细线被肥皂膜拉成弧形的实验现象",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp8","prereq":[
    k("毛细现象","实验直接展示毛细现象，没有概念就读不出",False),
    a("细管中液面变化观察","需要观察细管内外液面高度差的现象",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt49","prereq":[
    k("内能","绝热过程讨论系统内能变化，没有内能概念就读不出对象",False),
    m("控制变量","明确不与外界换热的过程条件，需要控制变量方法",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt50","prereq":[
    k("绝热过程","功与内能变化关系只发生在绝热条件下",False),
    m("能量守恒分析方法","用能量守恒推内能变化量，不知方法就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt51","prereq":[
    k("内能","热量与内能变化关系，没有内能概念就读不出",False),
    m("能量守恒分析方法","用守恒分析热量与内能变化，不知方法就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt52","prereq":[
    k("做功","功与热等价讨论的是做功改变内能,没有做功概念就读不出",False),
    k("传热","功与热等价讨论的是传热改变内能,没有传热概念就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp10","prereq":[
    k("电流","实验用电流加热液体，不知电流就读不出原理",False),
    k("传热","实验目的是说明电流做功转化为内能，不知传热就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp11","prereq":[
    k("绝热过程","空气快速压缩近似绝热,不知绝热概念就读不出条件",False),
    k("内能","压缩做功转化为内能使温度升高,不知内能就读不出机理",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp9","prereq":[
    k("重力","重物下落提供机械能,没有重力概念就读不出能量来源",False),
    k("内能","搅拌使水温升高即内能增加,不知内能就读不出变化",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl6","prereq":[
    k("能量","需要先理解能量概念才能区分转化与转移",False),
    m("分类辨析","需要从形式与路径两个维度对能量变化分类",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt53","prereq":[
    k("力","做功以力为基础,不知力就读不出做功",False),
    k("位移","做功以位移为基础,不知位移就读不出做功",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt54","prereq":[
    k("温度","传热源于温度差,不知温度就读不出传热",False),
    k("内能","传热改变系统内能,不知内能就读不出结果",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt55","prereq":[
    k("内能","定律核心是内能变化量,不知内能就读不出",False),
    k("做功","定律涉及外界做功项,不知做功就读不出",False),
    k("传热","定律涉及传热项,不知传热就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt56","prereq":[
    k("分子","热动说基于分子存在,不知分子就读不出",False),
    k("分子热运动","热动说核心是分子无规则运动,不知热运动就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt57","prereq":[
    k("物质","热质说把热当作一种物质,不知物质就读不出",False),
    a("流体直觉","需要把热类比为可流动物质的日常经验",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp12","prereq":[
    k("内能","焦耳实验测机械能与内能的当量,不知内能就读不出",False),
    k("热量","焦耳实验测定机械功转化为热量的数值,不知热量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp13","prereq":[
    k("摩擦","镗孔时摩擦使筒升温,不知摩擦就读不出原因",False),
    k("热量","摩擦生热是把机械能转为热,不知热量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt58","prereq":[
    k("能量守恒定律","永动机违背能量守恒,不知守恒定律就读不出",False),
    a("机械运转经验","需要见过机械不断输出动力又停止的生活观察",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt59","prereq":[
    k("能量","讨论对象是能量,不知能量就读不出",False),
    k("能量守恒定律","能量形式间转化保持总量不变,不知守恒就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt60","prereq":[
    k("能量","需要先理解能量概念,不知能量就读不出质能关系",False),
    k("质量","需要先理解质量概念,不知质量就读不出质能关系",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl7","prereq":[
    k("能量守恒定律","方法核心是守恒定律,不知定律就读不出",False),
    m("能量分析","需要在过程中辨识能量形式与数量变化的方法",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt61","prereq":[
    k("能量守恒定律","第二定律补充守恒定律的方向性限制",False),
    k("不可逆过程","定律描述不可逆过程的方向,不知不可逆就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt62","prereq":[
    k("传热","表述针对热量传递方向,不知传热就读不出",False),
    k("温度","表述涉及温度高低,不知温度就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt63","prereq":[
    k("热量","表述针对热量转化为功,不知热量就读不出",False),
    k("做功","表述讨论功与热的转化,不知做功就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt64","prereq":[
    k("系统","孤立系统是一种系统,不知系统就读不出",False),
    a("边界识别","需要能区分系统内外的边界意识",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt65","prereq":[
    k("微观态与宏观态","熵统计定义基于宏观态包含的微观态数,不知概念就读不出",False),
    k("分子热运动","熵联系分子运动无序度,不知热运动就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt66","prereq":[
    k("熵","原理针对熵的变化,不知熵就读不出",False),
    k("孤立系统","原理针对孤立系统,不知孤立系统就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt67","prereq":[
    k("分子","微观态由分子排布构成,不知分子就读不出",False),
    a("宏观与微观分辨","需要分清整体与局部两个层次的能力",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt68","prereq":[
    k("能量","耗散讨论能量的散失,不知能量就读不出",False),
    k("内能","耗散使分散的内能难再利用,不知内能就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt69","prereq":[
    k("黑体辐射","实验规律描述黑体辐射的波长分布,不知黑体辐射就读不出",False),
    k("波长","规律涉及波长位置,不知波长就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt70","prereq":[
    k("能量子","量子化基于能量字离散假设,不知能量子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt71","prereq":[
    k("能量","连续性讨论宏观能量取值,不知能量就读不出",False),
    a("连续变化经验","需要宏观物体能量连续变化的生活经验",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl8","prereq":[
    k("物理模型","方法核心是建立物理模型,不知模型就读不出",False),
    m("归纳","需要从实验数据归纳规律的推理方法",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt72","prereq":[
    k("光","光电效应是光照射金属的结果,不知光就读不出",False),
    k("电子","效应是电子从金属逸出,不知电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt73","prereq":[
    k("电子","光电子是电子,不知电子就读不出",False),
    k("光电效应","光电子从光电效应中产生,不知效应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt74","prereq":[
    k("频率","截止频率是频率阈值,不知频率就读不出",False),
    k("光电效应","截止频率是光电效应中的特征量,不知效应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt75","prereq":[
    k("电流","饱和电流是电流特征值,不知电流就读不出",False),
    k("光电效应","饱和电流在光电效应中达到最大,不知效应就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt76","prereq":[
    k("电压","遏止电压是电压值,不知电压就读不出",False),
    k("光电子","遏止电压使光电子减速为零,不知光电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt77","prereq":[
    k("电子","逸出功是电子逸出所需最小能量,不知电子就读不出",False),
    k("能量","逸出功是能量值,不知能量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt78","prereq":[
    k("光子","光子能量属于光子本身属性,不知光子就读不出",False),
    k("频率","光子能量由频率决定,不知频率就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt79","prereq":[
    k("光子能量","方程使用光子能量,不知能量就读不出",False),
    k("逸出功","方程使用逸出功,不知逸出功就读不出",False),
    k("动能","方程中含初动能项,不知动能就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt80","prereq":[
    k("光子","光子具有动量,不知光子就读不出",False),
    k("波长","动量由波长决定,不知波长就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt81","prereq":[
    k("光子的动量","康普顿用光子动量解释散射,不知动量就读不出",False),
    k("电子","散射涉及光子与电子碰撞,不知电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt82","prereq":[
    k("波动性","二象性包含波动性,不知波动就读不出",False),
    k("粒子性","二象性包含粒子性,不知粒子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp14","prereq":[
    k("光电效应","实验演示光电效应,不知效应就读不出",False),
    k("紫外线","实验光源是紫外线,不知紫外线就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_exp15","prereq":[
    k("光电效应","实验研究光电效应规律,不知效应就读不出",False),
    k("光电流","实验记录光电流大小,不知光电流就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_skl9","prereq":[
    k("爱因斯坦光电效应方程","方法基于方程,不知方程就读不出",False),
    m("图像分析","需要根据图线读取截止频率等参数的方法",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt83","prereq":[
    k("电场","阴极射线受电场偏转,不知电场就读不出偏转",False),
    k("磁场","阴极射线也受磁场作用,不知磁场就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt84","prereq":[
    k("阴极射线","电子是阴极射线的组成,不知射线就读不出",False),
    k("电荷量","电子的电荷量是基本量,不知电荷量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt85","prereq":[
    k("电荷量","比荷涉及电荷量,不知电荷量就读不出",False),
    k("质量","比荷涉及质量,不知质量就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt86","prereq":[
    k("电荷量","量子化针对电荷量,不知电荷量就读不出",False),
    k("电子","量子化的基本单位是电子电荷,不知电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt87","prereq":[
    k("原子","汤姆孙模型描述原子结构,不知原子就读不出对象",False),
    k("电子","模型需要安排电子位置,不知电子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt88","prereq":[
    k("粒子","散射实验用粒子轰击,不知粒子就读不出",False),
    k("原子","散射实验对象是金属箔中的原子,不知原子就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt89","prereq":[
    k("α粒子散射实验","模型直接基于实验结果,不知实验就读不出",False),
    k("原子核","模型核心是引入原子核,不知原子核就读不出",False),
],"dispute":[]})

entries.append({"id":"physics_xzxbx3_rjb_cpt90","prereq":[
    k("原子","原子核属于原子结构,不知原子就读不出",False),
    k("质子","原子核由质子构成,不知质子就读不出组成",False),
],"dispute":[]})

assert len(entries)==60, len(entries)
with open('data/lmm-out/physics-25.json','w',encoding='utf-8') as f:
    json.dump(entries,f,ensure_ascii=False,indent=1)
print(f'Written physics-25: {len(entries)} entries')
total_pre = sum(len(e.get('prereq',[])) for e in entries)
print(f'Total prereqs: {total_pre}')