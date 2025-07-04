import discord
from discord.ext import commands
import json
import os
from datetime import datetime
import asyncio
import random
import string
from dotenv import load_dotenv
import os

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Configurações (substitua pelos IDs do seu servidor)
CONFIG = {
    "GUILD_ID": 1390409777305092166,  # ID do seu servidor
    "TICKET_CATEGORY_ID": 1390409779570020420,  # ID da categoria onde os tickets serão criados
    "LOGS_CHANNEL_ID": 1390433781063618742,  # ID do canal onde os logs serão enviados
    "ROLE_REQUEST_CHANNEL_ID": 1390409777326329989,  # ID do canal onde o painel de cargos será enviado
    "ROLE_ADMIN_CHANNEL_ID": 1390434044864626728,  # ID do canal onde admins verão solicitações
    "AVAILABLE_ROLES": [  1390409777305092171,# IDs dos cargos disponíveis para solicitação
        # Exemplo: 123456789012345678
    ]
}

# Armazenamento de dados dos tickets
tickets_data = {}
role_requests = {}

def is_admin():
    """Verifica se o usuário tem permissões de administrador"""
    def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def save_ticket_log(ticket_id, messages):
    """Salva o log do ticket em arquivo"""
    if not os.path.exists('ticket_logs'):
        os.makedirs('ticket_logs')
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ticket_logs/ticket_{ticket_id}_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"=== LOG DO TICKET #{ticket_id} ===\n")
        f.write(f"Criado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write("=" * 50 + "\n\n")
        
        for msg in messages:
            f.write(f"[{msg['timestamp']}] {msg['author']}: {msg['content']}\n")
    
    return filename

@bot.event
async def on_ready():
    print(f'{bot.user} está online!')
    print(f'Conectado em {len(bot.guilds)} servidor(s)')
    
    # Sincroniza comandos slash
    try:
        synced = await bot.tree.sync()
        print(f'Sincronizados {len(synced)} comando(s) slash')
    except Exception as e:
        print(f'Erro ao sincronizar comandos: {e}')

    # Registra views persistentes (corrige o erro!)
    bot.add_view(TicketView())
    bot.add_view(RoleRequestView())
    bot.add_view(AdminPanelView())

# ========== SISTEMA DE CARGO AUTOMÁTICO ==========

@bot.event
async def on_member_join(member):
    """
    Evento disparado quando um membro entra no servidor
    Adiciona automaticamente o cargo inicial ao usuário
    """
    try:
        # ID do cargo que será dado automaticamente
        AUTO_ROLE_ID = 1390409777305092167
        
        # Busca o cargo no servidor
        auto_role = member.guild.get_role(AUTO_ROLE_ID)
        
        if auto_role:
            # Adiciona o cargo ao membro
            await member.add_roles(auto_role, reason='Cargo automático ao entrar no servidor')
            
            # Log opcional - pode ser removido se não quiser spam no console
            print(f'✅ Cargo automático adicionado para {member.name} ({member.id})')
            
        else:
            # Log de erro se o cargo não for encontrado
            print(f'❌ Cargo automático não encontrado! ID: {AUTO_ROLE_ID}')
            
    except discord.Forbidden:
        # Bot não tem permissão para adicionar cargos
        print(f'❌ Sem permissão para adicionar cargo automático para {member.name}')
        
    except discord.HTTPException as e:
        # Erro HTTP do Discord
        print(f'❌ Erro HTTP ao adicionar cargo automático: {e}')
        
    except Exception as e:
        # Qualquer outro erro
        print(f'❌ Erro inesperado ao adicionar cargo automático: {e}')

# ========== SISTEMA DE TICKETS ==========

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🎫 Criar Ticket', style=discord.ButtonStyle.primary, custom_id='create_ticket')
    async def create_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        
        # Verifica se o usuário já tem um ticket aberto
        # Busca por canais que começam com ticket- e contêm o display name do usuário
        user_display_name = user.display_name.lower()
        safe_name = ''.join(c for c in user_display_name if c.isalnum() or c in '-_')
        safe_name = safe_name[:20] if len(safe_name) > 20 else safe_name
        
        existing_ticket = discord.utils.get(guild.channels, name=f'ticket-{safe_name}')
        # Fallback: busca pelo ID também (caso já exista um ticket com ID)
        if not existing_ticket:
            existing_ticket = discord.utils.get(guild.channels, name=f'ticket-{user.id}')
        
        if existing_ticket:
            await interaction.response.send_message('Você já possui um ticket aberto!', ephemeral=True)
            return
        
        # Cria o canal do ticket
        category = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
        if not category:
            await interaction.response.send_message('Categoria de tickets não encontrada!', ephemeral=True)
            return
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Adiciona permissões para administradores
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        # Usa o apelido da pessoa no servidor (display_name)
        # Remove caracteres especiais para nome do canal
        user_display_name = user.display_name.lower()
        # Remove caracteres não permitidos em nomes de canais
        safe_name = ''.join(c for c in user_display_name if c.isalnum() or c in '-_')
        # Limita o tamanho do nome
        safe_name = safe_name[:20] if len(safe_name) > 20 else safe_name
        
        channel = await category.create_text_channel(
            name=f'ticket-{safe_name}',
            overwrites=overwrites
        )
        
        # Inicializa dados do ticket
        ticket_id = str(channel.id)
        tickets_data[ticket_id] = {
            'user_id': user.id,
            'channel_id': channel.id,
            'created_at': datetime.now().isoformat(),
            'messages': []
        }
        
        # Cria embed de boas-vindas
        embed = discord.Embed(
            title='🎫 Ticket Criado',
            description=f'Olá {user.mention}! Seu ticket foi criado com sucesso.\n\nDescreva seu problema ou dúvida que um admistrador da Antlove irá te ajudar em breve.',
            color=0x00ff00
        )
        embed.set_footer(text=f'Ticket ID: {ticket_id}')
        
        # Envia mensagem com botões de controle
        control_view = TicketControlView(ticket_id)
        await channel.send(embed=embed, view=control_view)
        
        await interaction.response.send_message(f'Ticket criado com sucesso! {channel.mention}', ephemeral=True)

class TicketControlView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
    
    @discord.ui.button(label='🔒 Fechar Ticket', style=discord.ButtonStyle.danger, custom_id='close_ticket')
    async def close_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Verifica se é administrador
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Apenas administradores podem fechar tickets!', ephemeral=True)
            return
        
        channel = interaction.channel
        ticket_data = tickets_data.get(self.ticket_id)
        
        if not ticket_data:
            await interaction.response.send_message('Dados do ticket não encontrados!', ephemeral=True)
            return
        
        # Coleta mensagens do canal
        messages = []
        async for message in channel.history(limit=None, oldest_first=True):
            if not message.author.bot or message.embeds:
                messages.append({
                    'timestamp': message.created_at.strftime('%d/%m/%Y %H:%M:%S'),
                    'author': str(message.author),
                    'content': message.content or '[Embed/Anexo]'
                })
        
        # Salva log
        log_file = save_ticket_log(self.ticket_id, messages)
        
        # Envia log para canal de logs
        logs_channel = interaction.guild.get_channel(CONFIG["LOGS_CHANNEL_ID"])
        if logs_channel:
            user = interaction.guild.get_member(ticket_data['user_id'])
            embed = discord.Embed(
                title='🔒 Ticket Fechado',
                description=f'**Usuário:** {user.mention if user else "Usuário não encontrado"}\n**Fechado por:** {interaction.user.mention}\n**Data:** {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}',
                color=0xff0000
            )
            embed.set_footer(text=f'Ticket ID: {self.ticket_id}')
            
            with open(log_file, 'rb') as f:
                file = discord.File(f, filename=f'ticket_log_{self.ticket_id}.txt')
                await logs_channel.send(embed=embed, file=file)
        
        # Remove dados do ticket
        del tickets_data[self.ticket_id]
        
        await interaction.response.send_message('Ticket será fechado em 5 segundos...')
        await asyncio.sleep(5)
        await channel.delete()

# ========== SISTEMA DE SOLICITAÇÃO DE CARGOS COM CAPTCHA ==========

import random
import string
import asyncio

# Dicionário para armazenar captchas pendentes
pending_captchas = {}

class RoleRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='📋 Solicitar Cargo', style=discord.ButtonStyle.secondary, custom_id='request_role')
    async def request_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        
        # Verifica se já tem uma solicitação pendente
        if user.id in role_requests:
            await interaction.response.send_message('Você já possui uma solicitação pendente!', ephemeral=True)
            return
        
        # Cria lista de cargos disponíveis
        available_roles = []
        for role_id in CONFIG["AVAILABLE_ROLES"]:
            role = guild.get_role(role_id)
            if role:
                available_roles.append(role)
        
        if not available_roles:
            await interaction.response.send_message('Nenhum cargo disponível para solicitação!', ephemeral=True)
            return
        
        # Cria view de captcha primeiro
        captcha_view = CaptchaView(available_roles)
        
        embed = discord.Embed(
            title='🔒 Verificação de Segurança',
            description=f'**Selecione o código correto:** `{captcha_view.captcha_code}`\n\nClique no botão que corresponde ao código mostrado acima.',
            color=0x830000
        )
        
        await interaction.response.send_message(embed=embed, view=captcha_view, ephemeral=True)

class CaptchaView(discord.ui.View):
    def __init__(self, available_roles):
        super().__init__(timeout=60)
        self.available_roles = available_roles
        
        # Gera um código captcha simples (4 caracteres alfanuméricos)
        self.captcha_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        
        # Gera opções incorretas para os botões
        wrong_options = []
        while len(wrong_options) < 3:
            wrong_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            if wrong_code != self.captcha_code and wrong_code not in wrong_options:
                wrong_options.append(wrong_code)
        
        # Mistura as opções (1 correta + 3 incorretas)
        all_options = [self.captcha_code] + wrong_options
        random.shuffle(all_options)
        
        # Cria botões para cada opção
        for i, option in enumerate(all_options):
            button = discord.ui.Button(
                label=option,
                style=discord.ButtonStyle.secondary,
                custom_id=f'captcha_option_{i}'
            )
            button.callback = self.create_callback(option)
            self.add_item(button)
    
    def create_callback(self, option):
        async def callback(interaction):
            if option == self.captcha_code:
                # Resposta correta - abre o modal diretamente
                modal = RoleRequestModal(self.available_roles)
                await interaction.response.send_modal(modal)
                
                # Cria uma task para apagar a mensagem após 5 segundos
                async def delete_message():
                    await asyncio.sleep(5)
                    try:
                        await interaction.delete_original_response()
                    except:
                        pass
                
                # Executa a task em segundo plano
                asyncio.create_task(delete_message())
                
            else:
                # Resposta incorreta
                error_embed = discord.Embed(
                    title='❌ Captcha Incorreto!',
                    description='Código errado! Tente novamente clicando no botão "Solicitar Cargo".',
                    color=0xff0000
                )
                await interaction.response.edit_message(embed=error_embed, view=None)
                
                # Apaga a mensagem após 5 segundos
                await asyncio.sleep(5)
                try:
                    await interaction.delete_original_response()
                except:
                    pass
        return callback
    
    async def on_timeout(self):
        # Desabilita todos os botões quando o timeout é atingido
        for item in self.children:
            item.disabled = True

class RoleRequestModal(discord.ui.Modal):
    def __init__(self, available_roles):
        super().__init__(title='Solicitar Cargo')
        self.available_roles = available_roles
        
        # Campo para nome do recrutador
        self.recruiter_name = discord.ui.TextInput(
            label='Nome do Recrutador',
            placeholder='Digite o nome de quem te recrutou...',
            style=discord.TextStyle.short,
            required=True,
            max_length=100
        )
        self.add_item(self.recruiter_name)
        
        # Campo para número ingame
        self.ingame_number = discord.ui.TextInput(
            label='Número Ingame',
            placeholder='Digite seu número ingame...',
            style=discord.TextStyle.short,
            required=True,
            max_length=50
        )
        self.add_item(self.ingame_number)
        
        # Campo para nome no RP
        self.rp_name = discord.ui.TextInput(
            label='Nome No RP',
            placeholder='Digite seu nome no roleplay...',
            style=discord.TextStyle.short,
            required=True,
            max_length=80
        )
        self.add_item(self.rp_name)
        
        # Campo para cargo desejado
        roles_text = '\n'.join([f'{i+1}. {role.name}' for i, role in enumerate(available_roles)])
        self.role_choice = discord.ui.TextInput(
            label=f'Número do cargo desejado:\n{roles_text}',
            placeholder='Digite o número do cargo desejado',
            style=discord.TextStyle.short,
            required=True,
            max_length=2
        )
        self.add_item(self.role_choice)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            choice = int(self.role_choice.value) - 1
            if choice < 0 or choice >= len(self.available_roles):
                await interaction.response.send_message('Número de cargo inválido!', ephemeral=True)
                return
            
            selected_role = self.available_roles[choice]
            user = interaction.user
            
            # Salva solicitação com os dados separados
            request_id = f"{user.id}_{int(datetime.now().timestamp())}"
            role_requests[user.id] = {
                'request_id': request_id,
                'user_id': user.id,
                'role_id': selected_role.id,
                'recruiter_name': self.recruiter_name.value,
                'ingame_number': self.ingame_number.value,
                'rp_name': self.rp_name.value,
                'timestamp': datetime.now().isoformat()
            }
            
            # Envia para canal de administradores
            admin_channel = interaction.guild.get_channel(CONFIG["ROLE_ADMIN_CHANNEL_ID"])
            if admin_channel:
                embed = discord.Embed(
                    title='📋 Nova Solicitação de Cargo',
                    description=f'**Usuário:** {user.mention}\n**Cargo solicitado:** {selected_role.mention}\n**Recrutador:** {self.recruiter_name.value}\n**Número Ingame:** {self.ingame_number.value}\n**Nome No RP:** {self.rp_name.value}',
                    color=0x830000
                )
                embed.set_thumbnail(url=user.avatar.url if user.avatar else None)
                embed.set_footer(text=f'Request ID: {request_id}')
                
                view = RoleAdminView(request_id)
                await admin_channel.send(embed=embed, view=view)
            
            await interaction.response.send_message('✅ Solicitação enviada com sucesso! Aguarde a aprovação dos administradores.', ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message('Por favor, digite apenas o número do cargo!', ephemeral=True)

class RoleAdminView(discord.ui.View):
    def __init__(self, request_id):
        super().__init__(timeout=None)
        self.request_id = request_id
    
    @discord.ui.button(label='✅ Aprovar', style=discord.ButtonStyle.success, custom_id='approve_role')
    async def approve_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Apenas administradores podem aprovar solicitações!', ephemeral=True)
            return
        
        # Encontra a solicitação
        request_data = None
        for _, data in role_requests.items():
            if data['request_id'] == self.request_id:
                request_data = data
                break
        
        if not request_data:
            await interaction.response.send_message('Solicitação não encontrada!', ephemeral=True)
            return
        
        user = interaction.guild.get_member(request_data['user_id'])
        role = interaction.guild.get_role(request_data['role_id'])
        
        if not user or not role:
            await interaction.response.send_message('Usuário ou cargo não encontrado!', ephemeral=True)
            return
        
        try:
            # Adiciona o cargo
            await user.add_roles(role, reason=f'Aprovado por {interaction.user}')
            
            # Remove o cargo inicial (ID: 1390409777305092167)
            initial_role = interaction.guild.get_role(1390409777305092167)
            if initial_role and initial_role in user.roles:
                try:
                    await user.remove_roles(initial_role, reason=f'Cargo inicial removido após aprovação por {interaction.user}')
                except discord.Forbidden:
                    # Se não conseguir remover, continua com o processo
                    pass
            
            # Renomeia o usuário com o formato: MEM | NOME DO RP
            new_nickname = f"MEM | {request_data['rp_name']}"
            try:
                await user.edit(nick=new_nickname, reason=f'Aprovação de cargo - {interaction.user}')
            except discord.Forbidden:
                # Se não conseguir renomear, continua com o processo
                pass
            
            # Remove solicitação
            del role_requests[request_data['user_id']]
            
            # Atualiza mensagem
            embed = discord.Embed(
                title='✅ Solicitação Aprovada',
                description=f'**Usuário:** {user.mention}\n**Cargo:** {role.mention}\n**Recrutador:** {request_data["recruiter_name"]}\n**Número Ingame:** {request_data["ingame_number"]}\n**Nome No RP:** {request_data["rp_name"]}\n**Novo Nickname:** {new_nickname}\n**Aprovado por:** {interaction.user.mention}',
                color=0x00ff00
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Notifica usuário
            try:
                await user.send(f'Sua solicitação para o cargo **{role.name}** foi aprovada!\nSeu nickname foi alterado para: **{new_nickname}**')
            except:
                pass
                
        except discord.Forbidden:
            await interaction.response.send_message('Não tenho permissão para adicionar este cargo!', ephemeral=True)
    
    @discord.ui.button(label='❌ Reprovar', style=discord.ButtonStyle.danger, custom_id='deny_role')
    async def deny_role(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Apenas administradores podem reprovar solicitações!', ephemeral=True)
            return
        
        # Encontra a solicitação
        request_data = None
        for user_id, data in role_requests.items():
            if data['request_id'] == self.request_id:
                request_data = data
                break
        
        if not request_data:
            await interaction.response.send_message('Solicitação não encontrada!', ephemeral=True)
            return
        
        user = interaction.guild.get_member(request_data['user_id'])
        role = interaction.guild.get_role(request_data['role_id'])
        
        # Remove solicitação
        del role_requests[request_data['user_id']]
        
        # Atualiza mensagem
        embed = discord.Embed(
            title='❌ Solicitação Reprovada',
            description=f'**Usuário:** {user.mention if user else "Usuário não encontrado"}\n**Cargo:** {role.mention if role else "Cargo não encontrado"}\n**Recrutador:** {request_data.get("recruiter_name", "N/A")}\n**Número Ingame:** {request_data.get("ingame_number", "N/A")}\n**Nome No RP:** {request_data.get("rp_name", "N/A")}\n**Reprovado por:** {interaction.user.mention}',
            color=0xff0000
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        # Notifica usuário
        if user:
            try:
                await user.send(f'Sua solicitação para o cargo **{role.name if role else "Desconhecido"}** foi reprovada.')
            except:
                pass

# ========== COMANDOS ==========

@bot.tree.command(name='setup_tickets', description='Configura o sistema de tickets')
@discord.app_commands.describe(channel='Canal onde o painel de tickets será enviado')
async def setup_tickets(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('Apenas administradores podem usar este comando!', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='🎫 Sistema de Tickets',
        description='Clique no botão abaixo para criar um ticket de suporte.\n\n**Como funciona:**\n• Clique em "Criar Ticket"\n• Um canal privado será criado para você\n• Descreva seu problema ou dúvida\n• Algum administrador irá te ajudar!',
        color=0xae0000
    )
    embed.set_footer(text='Sistema de Tickets - Clique no botão para começar')
    
    view = TicketView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f'Painel de tickets configurado em {channel.mention}!', ephemeral=True)

@bot.tree.command(name='setup_roles', description='Configura o sistema de solicitação de cargos')
@discord.app_commands.describe(channel='Canal onde o painel de cargos será enviado')
async def setup_roles(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('Apenas administradores podem usar este comando!', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='📋 Solicitação de Cargos',
        description='Clique no botão abaixo para solicitar um cargo.\n\n**Como funciona:**\n• Clique em "Solicitar Cargo"\n• Escolha o cargo desejado\n• Descreva quem te recrutou\n• Aguarde a aprovação dos administradores',
        color=0xcc3232
    )
    embed.set_footer(text='Sistema de Cargos - Clique no botão para solicitar')
    
    view = RoleRequestView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f'Painel de cargos configurado em {channel.mention}!', ephemeral=True)

@bot.tree.command(name='config', description='Mostra a configuração atual do bot')
async def config_command(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('Apenas administradores podem usar este comando!', ephemeral=True)
        return
    
    embed = discord.Embed(title='⚙️ Configuração do Bot', color=0xffd700)
    
    for key, value in CONFIG.items():
        if isinstance(value, list):
            embed.add_field(name=key, value=f'{len(value)} itens configurados', inline=True)
        else:
            embed.add_field(name=key, value=str(value), inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========== SISTEMA DE PAINEL DE ADMINISTRAÇÃO ==========

import discord
from discord.ext import commands
import json
import os
from datetime import datetime

# Arquivo para salvar advertências
WARNINGS_FILE = 'warnings.json'

def load_warnings():
    """Carrega as advertências do arquivo JSON"""
    if os.path.exists(WARNINGS_FILE):
        try:
            with open(WARNINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_warnings(warnings):
    """Salva as advertências no arquivo JSON"""
    try:
        with open(WARNINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(warnings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar advertências: {e}")

# ========== MODAIS ==========

class BanModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Sistema de Banimento")
        
        self.user_input = discord.ui.TextInput(
            label="Usuário (ID ou @menção)",
            placeholder="123456789012345678 ou @usuario",
            max_length=50,
            required=True
        )
        
        self.reason_input = discord.ui.TextInput(
            label="Motivo",
            placeholder="Motivo do banimento...",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )
        
        self.action_input = discord.ui.TextInput(
            label="Ação (ban/unban)",
            placeholder="ban ou unban",
            max_length=10,
            required=True
        )
        
        self.add_item(self.user_input)
        self.add_item(self.reason_input)
        self.add_item(self.action_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        user_id = self.user_input.value.replace('<', '').replace('>', '').replace('@', '').replace('!', '')
        reason = self.reason_input.value or "Não especificado"
        action = self.action_input.value.lower()
        
        try:
            if action == "ban":
                user = await interaction.guild.fetch_member(int(user_id))
                await user.ban(reason=reason)
                
                embed = discord.Embed(
                    title="✅ Usuário Banido",
                    description=f"**Usuário:** {user.mention}\n**Motivo:** {reason}",
                    color=0xff0000,
                    timestamp=datetime.now()
                )
                
            elif action == "unban":
                user = await interaction.client.fetch_user(int(user_id))
                await interaction.guild.unban(user, reason=reason)
                
                embed = discord.Embed(
                    title="✅ Usuário Desbanido",
                    description=f"**Usuário:** {user.mention}\n**Motivo:** {reason}",
                    color=0x00ff00,
                    timestamp=datetime.now()
                )
            else:
                await interaction.response.send_message("❌ Ação inválida! Use 'ban' ou 'unban'", ephemeral=True)
                return
                
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Erro: {str(e)}", ephemeral=True)

class RoleModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Gerenciamento de Cargos")
        
        self.user_input = discord.ui.TextInput(
            label="Usuário (ID ou @menção)",
            placeholder="123456789012345678 ou @usuario",
            max_length=50,
            required=True
        )
        
        self.role_input = discord.ui.TextInput(
            label="Cargo (Nome ou ID)",
            placeholder="Nome do cargo ou ID",
            max_length=100,
            required=True
        )
        
        self.action_input = discord.ui.TextInput(
            label="Ação (add/remove)",
            placeholder="add ou remove",
            max_length=10,
            required=True
        )
        
        self.add_item(self.user_input)
        self.add_item(self.role_input)
        self.add_item(self.action_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        user_id = self.user_input.value.replace('<', '').replace('>', '').replace('@', '').replace('!', '')
        role_name = self.role_input.value
        action = self.action_input.value.lower()
        
        try:
            member = await interaction.guild.fetch_member(int(user_id))
            role = discord.utils.get(interaction.guild.roles, name=role_name) or discord.utils.get(interaction.guild.roles, id=int(role_name) if role_name.isdigit() else None)
            
            if not role:
                await interaction.response.send_message("❌ Cargo não encontrado!", ephemeral=True)
                return
            
            if action == "add":
                await member.add_roles(role)
                embed = discord.Embed(
                    title="✅ Cargo Adicionado",
                    description=f"**Usuário:** {member.mention}\n**Cargo:** {role.mention}",
                    color=0x00ff00,
                    timestamp=datetime.now()
                )
                
            elif action == "remove":
                await member.remove_roles(role)
                embed = discord.Embed(
                    title="✅ Cargo Removido",
                    description=f"**Usuário:** {member.mention}\n**Cargo:** {role.mention}",
                    color=0xff9900,
                    timestamp=datetime.now()
                )
            else:
                await interaction.response.send_message("❌ Ação inválida! Use 'add' ou 'remove'", ephemeral=True)
                return
                
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Erro: {str(e)}", ephemeral=True)

class WarningModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Sistema de Advertências")
        
        self.user_input = discord.ui.TextInput(
            label="Usuário (ID ou @menção)",
            placeholder="123456789012345678 ou @usuario",
            max_length=50,
            required=True
        )
        
        self.reason_input = discord.ui.TextInput(
            label="Motivo",
            placeholder="Motivo da advertência...",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )
        
        self.action_input = discord.ui.TextInput(
            label="Ação (add/remove/view)",
            placeholder="add, remove ou view",
            max_length=10,
            required=True
        )
        
        self.add_item(self.user_input)
        self.add_item(self.reason_input)
        self.add_item(self.action_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        user_id = self.user_input.value.replace('<', '').replace('>', '').replace('@', '').replace('!', '')
        reason = self.reason_input.value or "Não especificado"
        action = self.action_input.value.lower()
        
        try:
            member = await interaction.guild.fetch_member(int(user_id))
            warnings = load_warnings()
            
            if user_id not in warnings:
                warnings[user_id] = []
            
            if action == "add":
                warnings[user_id].append({
                    'reason': reason,
                    'moderator': str(interaction.user.id),
                    'date': datetime.now().isoformat()
                })
                save_warnings(warnings)
                
                embed = discord.Embed(
                    title="⚠️ Advertência Adicionada",
                    description=f"**Usuário:** {member.mention}\n**Motivo:** {reason}\n**Total:** {len(warnings[user_id])} advertências",
                    color=0xffff00,
                    timestamp=datetime.now()
                )
                
            elif action == "remove":
                if warnings[user_id]:
                    warnings[user_id].pop()
                    save_warnings(warnings)
                    
                    embed = discord.Embed(
                        title="✅ Advertência Removida",
                        description=f"**Usuário:** {member.mention}\n**Advertências restantes:** {len(warnings[user_id])}",
                        color=0x00ff00,
                        timestamp=datetime.now()
                    )
                else:
                    await interaction.response.send_message("❌ Este usuário não possui advertências!", ephemeral=True)
                    return
                    
            elif action == "view":
                user_warnings = warnings.get(user_id, [])
                
                embed = discord.Embed(
                    title=f"📋 Advertências de {member.display_name}",
                    description=f"**Total:** {len(user_warnings)} advertências",
                    color=0x0099ff,
                    timestamp=datetime.now()
                )
                
                if user_warnings:
                    for i, warning in enumerate(user_warnings, 1):
                        date = datetime.fromisoformat(warning['date']).strftime('%d/%m/%Y %H:%M')
                        embed.add_field(
                            name=f"Advertência {i}",
                            value=f"**Motivo:** {warning['reason']}\n**Data:** {date}",
                            inline=False
                        )
                else:
                    embed.description = "Este usuário não possui advertências."
            else:
                await interaction.response.send_message("❌ Ação inválida! Use 'add', 'remove' ou 'view'", ephemeral=True)
                return
                
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Erro: {str(e)}", ephemeral=True)

class EmbedModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Criador de Embed")
        
        self.title_input = discord.ui.TextInput(
            label="Título",
            placeholder="Título do embed...",
            max_length=256,
            required=False
        )
        
        self.description_input = discord.ui.TextInput(
            label="Descrição",
            placeholder="Descrição do embed...",
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=False
        )
        
        self.fields_input = discord.ui.TextInput(
            label="Fields (Nome|Valor|Inline)",
            placeholder="Campo1|Valor1|True\nCampo2|Valor2|False",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )
        
        self.footer_input = discord.ui.TextInput(
            label="Footer",
            placeholder="Texto do footer...",
            max_length=2048,
            required=False
        )
        
        self.image_input = discord.ui.TextInput(
            label="URL da Imagem",
            placeholder="https://exemplo.com/imagem.png",
            max_length=500,
            required=False
        )
        
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.fields_input)
        self.add_item(self.footer_input)
        self.add_item(self.image_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(color=0x0099ff, timestamp=datetime.now())
        
        if self.title_input.value:
            embed.title = self.title_input.value
        
        if self.description_input.value:
            embed.description = self.description_input.value
        
        if self.footer_input.value:
            embed.set_footer(text=self.footer_input.value)
        
        if self.image_input.value:
            embed.set_image(url=self.image_input.value)
        
        if self.fields_input.value:
            fields = self.fields_input.value.split('\n')
            for field in fields:
                parts = field.split('|')
                if len(parts) >= 2:
                    name = parts[0]
                    value = parts[1]
                    inline = parts[2].lower() == 'true' if len(parts) > 2 else False
                    embed.add_field(name=name, value=value, inline=inline)
        
        await interaction.response.send_message("✅ Embed criado com sucesso!", ephemeral=True)
        await interaction.followup.send(embed=embed)

# ========== VIEW DO PAINEL ==========

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Necessário para persistência

    @discord.ui.button(
        label="Banimento",
        style=discord.ButtonStyle.danger,
        emoji="🔨",
        custom_id="adminpanel_ban_button"
    )
    async def ban_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar esta funcionalidade!", ephemeral=True
            )
            return

        await interaction.response.send_modal(BanModal())

    @discord.ui.button(
        label="Cargos",
        style=discord.ButtonStyle.primary,
        emoji="👑",
        custom_id="adminpanel_roles_button"
    )
    async def roles_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar esta funcionalidade!", ephemeral=True
            )
            return

        await interaction.response.send_modal(RoleModal())

    @discord.ui.button(
        label="Advertências",
        style=discord.ButtonStyle.secondary,
        emoji="⚠️",
        custom_id="adminpanel_warnings_button"
    )
    async def warnings_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar esta funcionalidade!", ephemeral=True
            )
            return

        await interaction.response.send_modal(WarningModal())

    @discord.ui.button(
        label="Embed",
        style=discord.ButtonStyle.success,
        emoji="📝",
        custom_id="adminpanel_embed_button"
    )
    async def embed_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar esta funcionalidade!", ephemeral=True
            )
            return

        await interaction.response.send_modal(EmbedModal())


# ========== COMANDOS ==========

@bot.tree.command(name='painel', description='Abre o painel de administração')
async def admin_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ Você não tem permissão para usar o painel de administração!', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='🛠️ Painel de Administração',
        description='Selecione uma opção abaixo para gerenciar o servidor:',
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    embed.add_field(
        name='🔨 Banimento',
        value='Banir/desbanir usuários do servidor',
        inline=True
    )
    
    embed.add_field(
        name='👑 Cargos',
        value='Adicionar/remover cargos de usuários',
        inline=True
    )
    
    embed.add_field(
        name='⚠️ Advertências',
        value='Gerenciar advertências dos usuários',
        inline=True
    )
    
    embed.add_field(
        name='📝 Embed',
        value='Criar embeds personalizados',
        inline=True
    )
    
    embed.set_footer(text='Painel de Administração')
    
    view = AdminPanelView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name='advertencias', description='Visualiza as advertências de um usuário')
@discord.app_commands.describe(usuario='Usuário para verificar as advertências')
async def view_warnings(interaction: discord.Interaction, usuario: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ Você não tem permissão para usar este comando!', ephemeral=True)
        return
    
    warnings = load_warnings()
    user_warnings = warnings.get(str(usuario.id), [])
    
    embed = discord.Embed(
        title=f'📋 Advertências de {usuario.display_name}',
        description=f'**Total:** {len(user_warnings)} advertências',
        color=0x0099ff,
        timestamp=datetime.now()
    )
    
    if user_warnings:
        for i, warning in enumerate(user_warnings, 1):
            date = datetime.fromisoformat(warning['date']).strftime('%d/%m/%Y %H:%M')
            embed.add_field(
                name=f'Advertência {i}',
                value=f"**Motivo:** {warning['reason']}\n**Data:** {date}",
                inline=False
            )
    else:
        embed.description = 'Este usuário não possui advertências.'
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='ban', description='Bane um usuário do servidor')
@discord.app_commands.describe(usuario='Usuário a ser banido', motivo='Motivo do banimento')
async def ban_user(interaction: discord.Interaction, usuario: discord.Member, motivo: str = "Não especificado"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message('❌ Você não tem permissão para banir usuários!', ephemeral=True)
        return
    
    try:
        await usuario.ban(reason=motivo)
        
        embed = discord.Embed(
            title='✅ Usuário Banido',
            description=f'**Usuário:** {usuario.mention}\n**Motivo:** {motivo}',
            color=0xff0000,
            timestamp=datetime.now()
        )
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(f'❌ Erro ao banir usuário: {str(e)}', ephemeral=True)

@bot.tree.command(name='unban', description='Desbane um usuário do servidor')
@discord.app_commands.describe(user_id='ID do usuário a ser desbanido', motivo='Motivo do desbanimento')
async def unban_user(interaction: discord.Interaction, user_id: str, motivo: str = "Não especificado"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message('❌ Você não tem permissão para desbanir usuários!', ephemeral=True)
        return
    
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=motivo)
        
        embed = discord.Embed(
            title='✅ Usuário Desbanido',
            description=f'**Usuário:** {user.mention}\n**Motivo:** {motivo}',
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(f'❌ Erro ao desbanir usuário: {str(e)}', ephemeral=True)

print("✅ Sistema de Painel de Administração carregado com sucesso!")

# ========== EVENTOS ==========

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Salva mensagens em tickets
    if message.channel.name and message.channel.name.startswith('ticket-'):
        ticket_id = str(message.channel.id)
        if ticket_id in tickets_data:
            tickets_data[ticket_id]['messages'].append({
                'timestamp': message.created_at.isoformat(),
                'author': str(message.author),
                'content': message.content
            })
    
    await bot.process_commands(message)



# ========== INICIALIZAÇÃO ==========

if __name__ == '__main__':
    from dotenv import load_dotenv
    import os

    load_dotenv()  # Carrega as variáveis do .env

    TOKEN = os.getenv("DISCORD_TOKEN")  # Lê o token do .env

    if not TOKEN:
        raise RuntimeError("⚠️  DISCORD_TOKEN não encontrado no .env!")

    print("🚀 Iniciando bot...")
    bot.run(TOKEN)
