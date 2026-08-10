# LearnerState v1 对接模板（ARCHIVE · LEGACY REFERENCE）

> **NOT RUNTIME · NOT SOURCE OF TRUTH · LEGACY REFERENCE**
>
> 本目录是**历史**「合作伙伴 Learner Model 对接模板」，仅存档参考。
> 运行时代码**绝不读取**本目录任何 JSON。

## 背景

早期设计曾假设「合作伙伴 Learner Model 是画像 Source of Truth，EduAgents 只读画像并回传事件」。
该前提已取消（合作伙伴画像系统尚未完成）。

当前架构：

- **本地 SQLite Dynamic Learner Model**（`data/learner_model.db`）是唯一画像真值。
- 画像由 LearningEvent → EvidenceExtractor → Updater 在本地维护，支持增删改/强化/弱化/失效/解决。
- 无任何外部画像服务、Remote Provider、Partner API 依赖。

## 保留原因

本模板保留了 v1 的字段设计（Profile / Goals / Preferences / Course Learner State /
Knowledge Mastery+Confidence / Misconception / Ability / Behavior），
可作为未来重建外部对接的字段参考，但**不参与当前运行**。

如需删除本目录，直接删除即可（无代码引用）。
