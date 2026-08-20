"""Stack CDK para a infraestrutura da Widevine PoC.

Recursos provisionados:
- CodeStar Connection: integração com GitHub
- SSM Parameter Store: storageState, channel URL
- S3 Bucket: artefatos (relatórios, evidências)
- CodeBuild Project: build e execução da PoC
- IAM Role: permissões para Bedrock, S3, SSM
"""
from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_codebuild as codebuild,
    aws_codestarconnections as codestar,
    aws_iam as iam,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct


class WidevinePoCStack(Stack):
    """Infraestrutura completa da Widevine PoC."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str = "widevine-poc",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ==============================================================
        # CodeStar Connection — GitHub
        # ==============================================================
        # Após o deploy, a connection fica em PENDING.
        # É necessário completar o handshake OAuth no console AWS:
        #   Developer Tools > Settings > Connections > Completar pendente
        github_connection = codestar.CfnConnection(
            self,
            "GitHubConnection",
            connection_name=f"{project_name}-github",
            provider_type="GitHub",
        )

        # ==============================================================
        # SSM Parameter Store — Configuração da PoC
        # ==============================================================

        # Parâmetro para URL do canal (pode ser alterado sem redeploy)
        channel_url_param = ssm.StringParameter(
            self,
            "ChannelUrlParam",
            parameter_name=f"/{project_name}/channel-url",
            string_value="https://www.skyplus.com.br/canal/ao-vivo",
            description="URL do canal SKY+ para monitoramento",
        )

        # Parâmetro para o storageState JSON (SecureString criado manualmente)
        # Nota: CDK não suporta criação de SecureString.
        # O valor deve ser inserido manualmente via console ou CLI:
        #   aws ssm put-parameter --name "/widevine-poc/storage-state-path" \
        #     --type "String" --value "s3://bucket/path/storageState.json"
        storage_state_param = ssm.StringParameter(
            self,
            "StorageStatePathParam",
            parameter_name=f"/{project_name}/storage-state-path",
            string_value="storage_state/state.json",
            description="Caminho para o arquivo storageState (local ou S3 key)",
        )

        # Parâmetro para nível de log
        log_level_param = ssm.StringParameter(
            self,
            "LogLevelParam",
            parameter_name=f"/{project_name}/log-level",
            string_value="INFO",
            description="Nível de log da PoC (DEBUG, INFO, WARNING, ERROR)",
        )

        # ==============================================================
        # S3 Bucket — Artefatos e storageState
        # ==============================================================

        artifacts_bucket = s3.Bucket(
            self,
            "ArtifactsBucket",
            bucket_name=f"{project_name}-artifacts-{self.account}",
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="cleanup-old-reports",
                    expiration=Duration.days(90),
                    prefix="output/",
                ),
            ],
        )

        # ==============================================================
        # IAM Role — CodeBuild com acesso a Bedrock, S3, SSM
        # ==============================================================

        codebuild_role = iam.Role(
            self,
            "CodeBuildRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            description="Role para execução da PoC Widevine no CodeBuild",
        )

        # Permissão para Amazon Bedrock (Claude Haiku e Sonnet)
        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvokeModel",
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
                ],
            )
        )

        # Permissão para ler Parameter Store
        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMReadParameters",
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                ],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/{project_name}/*",
                ],
            )
        )

        # Permissão para S3 (artefatos e storageState)
        artifacts_bucket.grant_read_write(codebuild_role)

        # Permissão para logs do CodeBuild
        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )

        # Permissão para usar a CodeStar Connection (GitHub)
        codebuild_role.add_to_policy(
            iam.PolicyStatement(
                sid="CodeStarConnection",
                effect=iam.Effect.ALLOW,
                actions=[
                    "codestar-connections:UseConnection",
                ],
                resources=[
                    github_connection.attr_connection_arn,
                ],
            )
        )

        # ==============================================================
        # CodeBuild Project — Execução da PoC
        # ==============================================================

        codebuild_project = codebuild.Project(
            self,
            "PoCProject",
            project_name=project_name,
            description="PoC de validação Widevine DRM com Playwright em container",
            role=codebuild_role,
            source=codebuild.Source.git_hub(
                owner="HudsonVRamos",
                repo="ChannelMonitoring",
                branch_or_ref="main",
                webhook=False,
                clone_depth=1,
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.MEDIUM,  # 7 GB RAM
                privileged=True,  # Necessário para shm_size do Chromium
            ),
            environment_variables={
                "POC_CHANNEL_URL": codebuild.BuildEnvironmentVariable(
                    value=channel_url_param.parameter_name,
                    type=codebuild.BuildEnvironmentVariableType.PARAMETER_STORE,
                ),
                "POC_STORAGE_STATE_PATH": codebuild.BuildEnvironmentVariable(
                    value=storage_state_param.parameter_name,
                    type=codebuild.BuildEnvironmentVariableType.PARAMETER_STORE,
                ),
                "POC_LOG_LEVEL": codebuild.BuildEnvironmentVariable(
                    value=log_level_param.parameter_name,
                    type=codebuild.BuildEnvironmentVariableType.PARAMETER_STORE,
                ),
                "POC_OUTPUT_DIR": codebuild.BuildEnvironmentVariable(
                    value="./output",
                    type=codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                ),
                "ARTIFACTS_BUCKET": codebuild.BuildEnvironmentVariable(
                    value=artifacts_bucket.bucket_name,
                    type=codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                ),
            },
            # Artefatos vão para S3
            artifacts=codebuild.Artifacts.s3(
                bucket=artifacts_bucket,
                include_build_id=True,
                package_zip=False,
                path="builds",
                name="latest",
            ),
            timeout=Duration.minutes(15),
            queued_timeout=Duration.minutes(30),
            # Cache de dependências Python e Playwright
            cache=codebuild.Cache.local(
                codebuild.LocalCacheMode.CUSTOM,
            ),
        )

        # ==============================================================
        # Outputs
        # ==============================================================

        CfnOutput(
            self,
            "CodeBuildProjectName",
            value=codebuild_project.project_name,
            description="Nome do projeto CodeBuild para execução da PoC",
        )

        CfnOutput(
            self,
            "ArtifactsBucketName",
            value=artifacts_bucket.bucket_name,
            description="Bucket S3 para artefatos e storageState",
        )

        CfnOutput(
            self,
            "ChannelUrlParamName",
            value=channel_url_param.parameter_name,
            description="SSM Parameter para URL do canal",
        )

        CfnOutput(
            self,
            "StartBuildCommand",
            value=f"aws codebuild start-build --project-name {project_name}",
            description="Comando para iniciar build manualmente",
        )

        CfnOutput(
            self,
            "GitHubConnectionArn",
            value=github_connection.attr_connection_arn,
            description=(
                "ARN da CodeStar Connection. "
                "Complete o handshake OAuth no console AWS após deploy."
            ),
        )
