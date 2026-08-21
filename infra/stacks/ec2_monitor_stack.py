"""Stack CDK para EC2 de monitoramento — Fase 1.

Provisiona uma EC2 t3.medium com:
- Ubuntu 22.04
- Google Chrome + Widevine
- Xvfb (display virtual)
- TigerVNC (acesso remoto visual)
- Python 3.11 + dependências do projeto
- Chrome profile persistente em EBS

Acesso via VNC: ssh tunnel + VNC client na porta 5901
"""
from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


# User data script para configurar a EC2 na primeira inicialização
USER_DATA_SCRIPT = """#!/bin/bash
set -e

echo "=== Atualizando sistema ==="
apt-get update -qq
export DEBIAN_FRONTEND=noninteractive

echo "=== Instalando dependências base ==="
apt-get install -y -qq \\
    python3.11 python3.11-venv python3-pip \\
    xvfb tigervnc-standalone-server tigervnc-common \\
    xfce4 xfce4-terminal dbus-x11 \\
    wget curl git unzip \\
    libnss3 libatk1.0-0 libatk-bridge2.0-0 \\
    libgbm1 libasound2 libxrandr2 \\
    libpango-1.0-0 libcairo2

echo "=== Instalando Google Chrome ==="
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
dpkg -i google-chrome-stable_current_amd64.deb || apt-get -fy install
rm google-chrome-stable_current_amd64.deb

echo "=== Configurando Python ==="
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
python3 -m pip install --upgrade pip
python3 -m pip install playwright boto3 opencv-python-headless numpy hypothesis pytest pytest-asyncio

echo "=== Instalando Playwright ==="
python3 -m playwright install-deps
# Não instalar chromium do Playwright — vamos usar Chrome do sistema

echo "=== Criando diretório para Chrome profile ==="
mkdir -p /data/chrome-profile
chown ubuntu:ubuntu /data/chrome-profile

echo "=== Configurando VNC ==="
mkdir -p /home/ubuntu/.vnc
echo "skymonitor" | vncpasswd -f > /home/ubuntu/.vnc/passwd
chmod 600 /home/ubuntu/.vnc/passwd
chown -R ubuntu:ubuntu /home/ubuntu/.vnc

cat > /home/ubuntu/.vnc/xstartup << 'EOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x /home/ubuntu/.vnc/xstartup
chown ubuntu:ubuntu /home/ubuntu/.vnc/xstartup

echo "=== Configurando Xvfb como serviço ==="
cat > /etc/systemd/system/xvfb.service << 'EOF'
[Unit]
Description=X Virtual FrameBuffer
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
EOF

echo "=== Configurando VNC como serviço ==="
cat > /etc/systemd/system/vncserver.service << 'EOF'
[Unit]
Description=TigerVNC Server
After=network.target xvfb.service

[Service]
Type=forking
User=ubuntu
ExecStart=/usr/bin/vncserver :1 -geometry 1920x1080 -depth 24
ExecStop=/usr/bin/vncserver -kill :1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

echo "=== Iniciando serviços ==="
systemctl daemon-reload
systemctl enable xvfb
systemctl start xvfb
systemctl enable vncserver
systemctl start vncserver

echo "=== Clonando repositório ==="
cd /home/ubuntu
sudo -u ubuntu git clone https://github.com/HudsonVRamos/ChannelMonitoring.git
cd ChannelMonitoring
sudo -u ubuntu python3 -m pip install -r requirements.txt

echo "=== Setup completo! ==="
echo "Acesse via: ssh -L 5901:localhost:5901 ubuntu@<IP>"
echo "Depois abra VNC client em localhost:5901"
echo "Senha VNC: skymonitor"
"""


class EC2MonitorStack(Stack):
    """EC2 para PoC de monitoramento — Fase 1."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str = "widevine-poc",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ==============================================================
        # VPC — VPC simples com subnet pública
        # ==============================================================
        vpc = ec2.Vpc(
            self,
            "MonitorVpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # ==============================================================
        # Security Group — SSH apenas
        # ==============================================================
        sg = ec2.SecurityGroup(
            self,
            "MonitorSG",
            vpc=vpc,
            description="SG para EC2 de monitoramento SKY+",
            allow_all_outbound=True,
        )
        # SSH (VNC será via tunnel SSH, não expor porta 5901)
        sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(22),
            "SSH access",
        )
        # RDP (xrdp para acesso remoto visual)
        sg.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(3389),
            "RDP access",
        )

        # ==============================================================
        # IAM Role — Bedrock + S3 + SSM
        # ==============================================================
        role = iam.Role(
            self,
            "MonitorRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
            ],
        )

        # Bedrock
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )

        # S3 — bucket de artefatos existente
        artifacts_bucket = s3.Bucket.from_bucket_name(
            self,
            "ArtifactsBucket",
            f"{project_name}-artifacts-us-east-1-{self.account}",
        )
        artifacts_bucket.grant_read_write(role)

        # ==============================================================
        # EC2 Instance — t3.medium com Ubuntu 22.04
        # ==============================================================
        instance = ec2.Instance(
            self,
            "MonitorInstance",
            instance_type=ec2.InstanceType("t3.large"),
            machine_image=ec2.MachineImage.generic_linux(
                ami_map={
                    "us-east-1": "ami-0c7217cdde317cfec",  # Ubuntu 22.04 LTS
                    "sa-east-1": "ami-0a8d820d3a2ad655a",  # Ubuntu 22.04 LTS
                }
            ),
            vpc=vpc,
            security_group=sg,
            role=role,
            key_name="widevine-poc-key",
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/sda1",
                    volume=ec2.BlockDeviceVolume.ebs(
                        30,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=False,
                    ),
                )
            ],
            user_data=ec2.UserData.custom(USER_DATA_SCRIPT),
        )

        # ==============================================================
        # Outputs
        # ==============================================================
        CfnOutput(
            self,
            "InstanceId",
            value=instance.instance_id,
            description="ID da instância EC2",
        )

        CfnOutput(
            self,
            "PublicIP",
            value=instance.instance_public_ip,
            description="IP público da instância",
        )

        CfnOutput(
            self,
            "SSHCommand",
            value=f"ssh -L 5901:localhost:5901 ubuntu@<PUBLIC_IP>",
            description="Comando SSH com tunnel VNC",
        )

        CfnOutput(
            self,
            "VNCInfo",
            value="Após SSH tunnel, conectar VNC em localhost:5901 (senha: skymonitor)",
            description="Instruções de acesso VNC",
        )
