# Tasks: amazon-rufus new Chrome launch

- [x] 在 CLI 层新增 `--new-chrome` 参数并传入 manager。
- [x] 在 `RufusManager.get()` 增加 `new_chrome` 入参并传给浏览器连接服务。
- [x] 在 Chrome/CDP 连接服务中实现固定命令启动与 CDP 轮询。
- [x] 更新 `ops-amazon-rufus` README/SKILL 使用示例。
- [x] 增加或更新定向测试，覆盖参数传递和启动分支。
- [x] 运行相关测试验证行为不回退。
