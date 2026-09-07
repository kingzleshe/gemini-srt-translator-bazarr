# 项目协作规则

## 运行环境

- 服务通过 Docker 运行在 `192.168.1.1`，容器名为 `gemini-srt-translator-bazarr`，Web 端口为 `6789`。
- SSH 登录命令：`ssh root@192.168.1.1`。SSH 连接设备时在沙箱外执行，并遵守当前工具的权限配置。
- 宿主机服务数据目录：`/opt/docker/gemini-srt-translator-bazarr`。
- 宿主机队列目录：`/opt/docker/bazarr/postprocess/queue`，映射到容器 `/queue`。
- Bazarr 入队脚本：`/opt/docker/bazarr/postprocess/gst_enqueue.sh`。

## 构建与部署

- 镜像通过 GitHub 构建。默认工作范围是修改仓库代码、运行相关测试并报告结果；不在本机或远程设备上构建镜像。
- 需要了解线上状态时，可通过 SSH 做只读检查。修改代码的请求不代表授权部署；只有用户明确要求更新运行服务时，才修改容器文件、替换远程脚本、重启或重建容器。
- 部署沿用 GitHub 构建的镜像流程。若用户明确要求临时直接修改容器，先备份受影响文件，并说明普通重启会保留修改，但使用镜像重建容器会覆盖容器内的修改。
- 报告时明确区分仓库代码已修改、GitHub 镜像已构建、运行容器已更新；只宣称已经验证的状态。
