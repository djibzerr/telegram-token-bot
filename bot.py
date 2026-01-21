import os
import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
import logging

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from web3 import Web3
from eth_utils import is_address

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8285852300:AAH0bsgjQhve6IhcX04T9xGZjaY_8nyCdGU")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "GTDF3H4BDJIWGUMIW6CXDQWRH4Q9HAYEJ5")
BASESCAN_API_KEY = os.getenv("BASESCAN_API_KEY", "GTDF3H4BDJIWGUMIW6CXDQWRH4Q9HAYEJ5")
INFURA_KEY = os.getenv("INFURA_KEY", "703284f78ae24e16a723f8f837832fde")

# Web3 providers
PROVIDERS = {
    "ethereum": f"https://mainnet.infura.io/v3/{INFURA_KEY}",
    "base": "https://mainnet.base.org",
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "optimism": "https://mainnet.optimism.io",
}

# Adresses connues de Factory/Router des plateformes BASE
PLATFORM_ADDRESSES = {
    "uniswap_v2_router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
    "uniswap_v3_factory": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
    "aerodrome": "0xcf77a3ba9a5ca399b7c97c74d54e5b1beb874e43",
    "baseswap": "0x327df1e6de05895d2ab08513aadd9313fe505d86",
    "sushiswap": "0x6BDED42c6DA8FBf0d2bA55B2fa120C5e0c8D7891",
    "pancakeswap": "0x02a84c5b5a2d569e2a1e1e18d1d42f7e4b2f1e1e",
}

# Plateformes de lancement sur BASE
LAUNCHPAD_PLATFORMS = [
    {"name": "Clanker", "url_template": "https://www.clanker.world/clanker/{address}"},
    {"name": "Zora", "url_template": "https://zora.co/collect/base:{address}"},
    {"name": "Ape.store", "url_template": "https://ape.store/base/{address}"},
    {"name": "Klik", "url_template": "https://klik.network/token/{address}"},
    {"name": "WOW", "url_template": "https://wow.xyz/token/base/{address}"},
    {"name": "Base.app", "url_template": "https://base.app/token/{address}"},
]

class TokenAnalyzer:
    def __init__(self):
        self.session = None
        
    async def init_session(self):
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close_session(self):
        if self.session:
            await self.session.close()
    
    def detect_chain(self, address: str) -> str:
        """Détecte la chaîne (pour l'instant on assume BASE)"""
        return "base"
    
    async def get_token_info(self, address: str, chain: str) -> Dict:
        """Récupère les informations basiques du token"""
        try:
            w3 = Web3(Web3.HTTPProvider(PROVIDERS[chain]))
            
            # ABI minimal pour ERC20
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            ]
            
            contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=erc20_abi)
            
            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            total_supply = contract.functions.totalSupply().call()
            
            # Formater le total supply
            total_supply_formatted = total_supply / (10 ** decimals)
            
            return {
                "name": name,
                "symbol": symbol,
                "decimals": decimals,
                "total_supply": f"{total_supply_formatted:,.0f}",
                "address": address,
                "chain": chain
            }
        except Exception as e:
            logger.error(f"Erreur get_token_info: {e}")
            return {"error": str(e)}
    
    async def detect_platform(self, address: str, chain: str) -> List[Dict]:
        """Détecte les plateformes où le token est présent"""
        detected = []
        
        # Check sur les launchpads connus
        for platform in LAUNCHPAD_PLATFORMS:
            url = platform["url_template"].format(address=address)
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    # On vérifie juste si la page existe et retourne 200
                    if resp.status == 200:
                        content = await resp.text()
                        # Vérification basique qu'il y a du contenu pertinent
                        if len(content) > 1000:  # Page avec du contenu
                            detected.append({
                                "name": platform["name"],
                                "url": url
                            })
            except Exception as e:
                logger.debug(f"Platform {platform['name']} check failed: {e}")
                continue
        
        # Toujours ajouter Uniswap et DEXScreener comme fallback
        detected.append({
            "name": "Uniswap",
            "url": f"https://app.uniswap.org/explore/tokens/{chain}/{address}"
        })
        
        return detected
    
    async def search_social_mentions(self, ticker: str) -> List[str]:
        """Recherche les mentions du ticker sur les réseaux sociaux"""
        mentions = []
        
        mentions.append(f"🔍 [Twitter/X](https://twitter.com/search?q=%24{ticker}&f=live)")
        mentions.append(f"🔍 [Farcaster](https://warpcast.com/~/search?q=%24{ticker})")
        
        return mentions
    
    async def get_contract_creation_tx(self, token_address: str, chain: str) -> Optional[Dict]:
        """Récupère la transaction de création du contrat"""
        try:
            if chain == "base":
                url = f"https://api.basescan.org/api"
                params = {
                    "module": "contract",
                    "action": "getcontractcreation",
                    "contractaddresses": token_address,
                    "apikey": BASESCAN_API_KEY
                }
            elif chain == "ethereum":
                url = f"https://api.etherscan.io/api"
                params = {
                    "module": "contract",
                    "action": "getcontractcreation",
                    "contractaddresses": token_address,
                    "apikey": ETHERSCAN_API_KEY
                }
            else:
                return None
            
            async with self.session.get(url, params=params) as resp:
                data = await resp.json()
                if data.get("status") == "1" and data.get("result"):
                    result = data["result"][0]
                    return {
                        "deployer": result.get("contractCreator"),
                        "tx_hash": result.get("txHash")
                    }
        except Exception as e:
            logger.error(f"Erreur get_contract_creation_tx: {e}")
        
        return None
    
    async def get_deployer_tokens(self, deployer_address: str, current_token: str, chain: str, limit: int = 5) -> List[Dict]:
        """Récupère les tokens créés par le déployeur"""
        try:
            if chain == "base":
                url = f"https://api.basescan.org/api"
                api_key = BASESCAN_API_KEY
            elif chain == "ethereum":
                url = f"https://api.etherscan.io/api"
                api_key = ETHERSCAN_API_KEY
            else:
                return []
            
            params = {
                "module": "account",
                "action": "txlist",
                "address": deployer_address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 100,
                "sort": "desc",
                "apikey": api_key
            }
            
            async with self.session.get(url, params=params) as resp:
                data = await resp.json()
                
                if data.get("status") != "1":
                    logger.warning(f"API returned status: {data.get('message')}")
                    return []
                
                created_tokens = []
                seen_addresses = set()
                
                for tx in data.get("result", []):
                    # Transaction de création de contrat
                    if tx.get("to") == "" and tx.get("contractAddress"):
                        contract_addr = tx["contractAddress"]
                        
                        # Skip le token actuel et les doublons
                        if contract_addr.lower() == current_token.lower():
                            continue
                        if contract_addr in seen_addresses:
                            continue
                        
                        seen_addresses.add(contract_addr)
                        
                        try:
                            # Essayer de récupérer les infos du token
                            token_info = await self.get_token_info(contract_addr, chain)
                            if "error" not in token_info:
                                created_tokens.append({
                                    "name": token_info["name"],
                                    "symbol": token_info["symbol"],
                                    "address": contract_addr,
                                    "timestamp": datetime.fromtimestamp(int(tx["timeStamp"])).strftime("%Y-%m-%d %H:%M")
                                })
                                
                                if len(created_tokens) >= limit:
                                    break
                        except Exception as e:
                            logger.debug(f"Could not get token info for {contract_addr}: {e}")
                            continue
                
                return created_tokens
        except Exception as e:
            logger.error(f"Erreur get_deployer_tokens: {e}")
            return []
    
    async def get_funding_address(self, deployer_address: str, chain: str) -> Optional[str]:
        """Récupère l'adresse qui a financé le déployeur (première transaction entrante)"""
        try:
            if chain == "base":
                url = f"https://api.basescan.org/api"
                api_key = BASESCAN_API_KEY
            elif chain == "ethereum":
                url = f"https://api.etherscan.io/api"
                api_key = ETHERSCAN_API_KEY
            else:
                return None
            
            params = {
                "module": "account",
                "action": "txlist",
                "address": deployer_address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 10,
                "sort": "asc",
                "apikey": api_key
            }
            
            async with self.session.get(url, params=params) as resp:
                data = await resp.json()
                
                if data.get("status") == "1" and data.get("result"):
                    # Cherche la première transaction entrante avec de la valeur
                    for tx in data["result"]:
                        if tx["to"].lower() == deployer_address.lower() and int(tx.get("value", 0)) > 0:
                            return tx["from"]
        except Exception as e:
            logger.error(f"Erreur get_funding_address: {e}")
        
        return None
    
    def create_buttons(self, address: str, chain: str) -> InlineKeyboardMarkup:
        """Crée les boutons pour les liens rapides"""
        keyboard = [
            [
                InlineKeyboardButton("📊 DEXScreener", url=f"https://dexscreener.com/{chain}/{address}"),
                InlineKeyboardButton("📈 GMGN", url=f"https://gmgn.ai/sol/token/{address}")
            ],
            [
                InlineKeyboardButton("🔍 Basescan", url=f"https://basescan.org/token/{address}"),
                InlineKeyboardButton("🦄 Uniswap", url=f"https://app.uniswap.org/explore/tokens/{chain}/{address}")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def analyze_token(self, address: str) -> tuple[str, InlineKeyboardMarkup]:
        """Analyse complète d'un token"""
        await self.init_session()
        
        result = "🔍 **ANALYSE DU TOKEN**\n\n"
        
        # Validation de l'adresse
        if not is_address(address):
            return ("❌ Adresse de contrat invalide", None)
        
        # Détection de la chaîne
        chain = self.detect_chain(address)
        result += f"⛓️ **Chaîne:** {chain.upper()}\n"
        result += f"📝 **Adresse:** `{address}`\n\n"
        
        # Informations du token
        result += "📊 **INFORMATIONS DU TOKEN**\n"
        token_info = await self.get_token_info(address, chain)
        if "error" not in token_info:
            result += f"• Nom: {token_info['name']}\n"
            result += f"• Symbole: ${token_info['symbol']}\n"
            result += f"• Supply Total: {token_info['total_supply']}\n\n"
            ticker = token_info['symbol']
        else:
            result += f"❌ Impossible de récupérer les infos du token\n\n"
            ticker = "UNKNOWN"
        
        # Détection de la plateforme (simplifiée - ne vérifie plus activement)
        result += "🌐 **LIENS RAPIDES**\n"
        result += f"• [DEXScreener](https://dexscreener.com/{chain}/{address})\n"
        result += f"• [GMGN](https://gmgn.ai/sol/token/{address})\n"
        result += f"• [Basescan](https://basescan.org/token/{address})\n"
        result += f"• [Uniswap](https://app.uniswap.org/explore/tokens/{chain}/{address})\n\n"
        
        # Launchpads potentiels
        result += "🚀 **LAUNCHPADS POSSIBLES**\n"
        for platform in LAUNCHPAD_PLATFORMS:
            url = platform["url_template"].format(address=address)
            result += f"• [{platform['name']}]({url})\n"
        result += "\n"
        
        # Mentions sociales
        result += f"💬 **RECHERCHE SOCIALE (${ticker})**\n"
        mentions = await self.search_social_mentions(ticker)
        for mention in mentions:
            result += f"• {mention}\n"
        result += "\n"
        
        # Analyse du déployeur
        result += "👤 **ANALYSE DU DÉPLOYEUR**\n"
        creation_info = await self.get_contract_creation_tx(address, chain)
        
        if creation_info and creation_info.get("deployer"):
            deployer = creation_info["deployer"]
            result += f"• Adresse: `{deployer}`\n"
            result += f"• [Voir sur Basescan](https://basescan.org/address/{deployer})\n\n"
            
            # Tokens précédents du déployeur
            result += "📋 **Tokens créés par ce déployeur (max 5):**\n"
            deployer_tokens = await self.get_deployer_tokens(deployer, address, chain, 5)
            
            if deployer_tokens:
                for token in deployer_tokens:
                    result += f"  • {token['name']} (${token['symbol']}) - {token['timestamp']}\n"
                    result += f"    `{token['address']}`\n"
            else:
                result += "  • Aucun autre token trouvé récemment\n"
            
            # Analyse du wallet de financement
            result += "\n💰 **WALLET DE FINANCEMENT**\n"
            funder = await self.get_funding_address(deployer, chain)
            
            if funder and funder.lower() != deployer.lower():
                result += f"• Adresse: `{funder}`\n"
                result += f"• [Voir sur Basescan](https://basescan.org/address/{funder})\n\n"
                
                result += "📋 **Tokens créés par le wallet de financement (max 5):**\n"
                funder_tokens = await self.get_deployer_tokens(funder, address, chain, 5)
                
                if funder_tokens:
                    for token in funder_tokens:
                        result += f"  • {token['name']} (${token['symbol']}) - {token['timestamp']}\n"
                        result += f"    `{token['address']}`\n"
                else:
                    result += "  • Aucun token trouvé\n"
            else:
                result += "• Wallet auto-financé ou données non disponibles\n"
        else:
            result += "• Informations du déployeur non disponibles sur cette chaîne\n"
        
        # Créer les boutons
        buttons = self.create_buttons(address, chain)
        
        return (result, buttons)

# Handlers Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    welcome_message = """
🤖 **Bot d'Analyse de Tokens EVM**

Envoyez-moi une adresse de contrat BASE et je vais analyser :

✅ Informations du token (nom, symbole, supply)
✅ Liens vers toutes les plateformes (DEXScreener, GMGN, Basescan, etc.)
✅ Recherche sociale du ticker
✅ Historique du déployeur (tokens précédents)
✅ Analyse du wallet de financement

**Exemple:**
`0x4ed4e862860bed51a9570b96d89af5e1b0efefed`

Envoyez simplement l'adresse et c'est parti ! 🚀
"""
    await update.message.reply_text(welcome_message, parse_mode="Markdown")

async def analyze_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyse un message contenant une adresse"""
    text = update.message.text.strip()
    
    # Extrait l'adresse Ethereum du message
    eth_address_pattern = r'0x[a-fA-F0-9]{40}'
    matches = re.findall(eth_address_pattern, text)
    
    if not matches:
        await update.message.reply_text(
            "❌ Aucune adresse de contrat valide détectée.\n\n"
            "Format attendu: 0x suivi de 40 caractères hexadécimaux"
        )
        return
    
    address = matches[0]
    
    # Message de chargement
    loading_msg = await update.message.reply_text("🔄 Analyse en cours... Cela peut prendre 10-20 secondes.")
    
    # Analyse
    analyzer = TokenAnalyzer()
    try:
        result, buttons = await analyzer.analyze_token(address)
        await loading_msg.edit_text(
            result, 
            parse_mode="Markdown",
            reply_markup=buttons,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse: {e}", exc_info=True)
        await loading_msg.edit_text(f"❌ Erreur lors de l'analyse: {str(e)}")
    finally:
        await analyzer.close_session()

def main():
    """Point d'entrée principal"""
    # Créer l'application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Ajouter les handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_message))
    
    # Démarrer le bot
    logger.info("🤖 Bot démarré!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
