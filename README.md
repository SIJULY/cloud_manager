# 一款强大的Cloud Manager 三合一面板

一个强大且便捷的网页管理面板，旨在将 **Amazon Web Services (AWS)**、**Microsoft Azure** 和 **Oracle Cloud Infrastructure (OCI)** 的核心虚拟机管理功能整合到一个统一的界面中。  

本项目由 **小龙女她爸** & **雨后大佬** 共同开发，旨在简化云资源的管理流程。

---

## ✨ 主要特性

- **三合一管理**: 在一个网页中无缝切换和管理您的 AWS, Azure, 和 OCI 云资源。  
- **账户管理**: 安全地添加和管理多个云服务商的账户凭证。  
- **实例操作**: 对虚拟机执行常用操作，如启动、停止、重启和删除。  
- **一键创建**: 简化了在各个云平台上创建虚拟机的流程。  
- **后台任务队列**: 对于耗时较长的操作（如 OCI 抢占实例），使用后台任务队列进行处理，不阻塞界面。  
- **动态资源加载**: 实时查询和展示虚拟机、区域、配额等信息。  
- **一键安装**: 提供自动化脚本，可在全新的服务器上快速完成所有环境配置和部署。  

---
<img width="1894" height="1908" alt="4ad1dc3d-a708-4fa2-9a5b-0b86ab39123e" src="https://github.com/user-attachments/assets/17cbbf28-0bf8-44c5-a72d-57b4539ac934" />

<img width="1834" height="1884" alt="9d39cf65-3dfa-4ac5-a79c-06926f3f3c74" src="https://github.com/user-attachments/assets/b2d1e655-e903-45bc-bd8b-878d84cf8f18" />

<img width="1901" height="1799" alt="3394f3cc-0ae0-4c55-a4f3-8e57ddf7d684" src="https://github.com/user-attachments/assets/203baebc-e9f7-400f-9a39-514d51de168d" />

<img width="1918" height="1626" alt="image" src="https://github.com/user-attachments/assets/e7c654ef-3ce7-4f7e-b60b-00f9e59f8b3a" />

<img width="1924" height="1606" alt="image" src="https://github.com/user-attachments/assets/cb14db44-9ec2-4493-a658-906ba14af789" />

<img width="1921" height="1613" alt="image" src="https://github.com/user-attachments/assets/a26e779b-2f83-4d24-9ba8-4dbb36286a4a" />

<img width="1921" height="1534" alt="image" src="https://github.com/user-attachments/assets/fcd7ca55-b2c4-491b-9327-86175697d172" />








## 🚀 一键快速安装

本项目提供了一个自动化安装脚本，适用于一个全新的、基于 **Debian** 或 **Ubuntu** 的服务器。  

请以 `root` 用户身份登录您的服务器，然后执行以下一行命令（安装/更新，卸载）：

DOCKER版本（推荐版本）
```bash
bash <(curl -sL https://raw.githubusercontent.com/SIJULY/cloud_manager/main/docker-install.sh)
```

TGBOT控制面板（可选）
```bash
bash <(curl -sL https://raw.githubusercontent.com/SIJULY/tgbot/main/install_tgbot.sh)
```

```bash
bash <(curl -sL https://raw.githubusercontent.com/SIJULY/cloud_manager/main/install.sh)
```

脚本将会引导您完成以下操作：

1. 自动安装所有系统和 Python 依赖。  
2. 配置并启动 **Caddy** 作为反向代理 Web 服务器。  
3. 配置并启动 **Gunicorn (Web App)** 和 **Celery (任务队列)** 后台服务。  
4. 提示您设置自定义的登录密码。  
5. 提示您输入域名或自动使用服务器公网 IP。  

---

## 🔑 API 密钥/凭证获取教程

要使用此面板，您需要从各个云服务商获取相应的 API 访问凭证。详细的图文教程，例如如何创建 IAM 用户、如何注册 Azure 应用等，可以在以下原始独立项目的仓库中找到：

- **AWS 面板** (获取 Access Key & Secret Key)  
  👉 [https://github.com/SIJULY/aws](https://github.com/SIJULY/aws)

- **Azure 面板** (获取 客户端ID, 密码, 租户ID, 订阅ID)  
  👉 [https://github.com/SIJULY/azure](https://github.com/SIJULY/azure)

- **OCI 面板** (获取 User/Tenancy OCID, Fingerprint, Region & PEM 私钥)  
  👉 [https://github.com/SIJULY/Oracle](https://github.com/SIJULY/Oracle)

---

## 📝 使用说明

1. **访问**: 安装完成后，通过脚本最后提示的域名或 IP 地址访问您的面板。  
2. **登录**: 使用您在安装过程中设置的密码进行登录。  
3. **添加账户**: 分别在各个云平台的页面上，添加您获取到的 API 凭证。  
4. **开始管理**: 选择一个已添加的账户进行连接，即可开始管理您的云资源。  

---

## ❤️ 致谢

 **所有拥有共享精神的开发者**
