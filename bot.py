import os
import re
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
import aiohttp
from telegram import Update
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

class TokenAnalyzer:
    def __init__(self):
        self.session = None
        
    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def close_session(self):
        if self.session:
            await self.session.close()
    
    def detect_chain(self, address: str) -> str:
        """Détecte la chaîne probable basée sur l'activité"""
        # Par défaut, on commence par Base (populaire pour les nouveaux tokens)
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
            
            return {
                "name": name,
                "symbol": symbol,
                "decimals": decimals,
                "total_supply": total_supply,
                "address": address,
                "chain": chain
            }
        except Exception as e:
            return {"error": str(e)}
    
    async def detect_platform(self, address: str, chain: str) -> Dict:
        """Détecte la plateforme de création du token"""
        platforms = {
            "clanker": {
                "url": f"https://www.clanker.world/clanker/{address}",
                "check": lambda: self._check_clanker(address)
            },
            "farcaster": {
                "url": f"https://warpcast.com/~/search?q={address}",
                "check": lambda: self._check_farcaster(address)
            },
            "baseapp": {
                "url": f"https://base.app/token/{address}",
                "check": lambda: self._check_baseapp(address)
            },
            "uniswap": {
                "url": f"https://app.uniswap.org/explore/tokens/{chain}/{address}",
                "check": lambda: self._check_uniswap(address, chain)
            }
        }
        
        detected_platforms = []
        
        for platform_name, platform_info in platforms.items():
            try:
                if await platform_info["check"]():
                    detected_platforms.append({
                        "name": platform_name,
                        "url": platform_info["url"]
                    })
            except:
                pass
        
        return {
            "platforms": detected_platforms,
            "primary_url": detected_platforms[0]["url"] if detected_platforms else None
        }
    
    async def _check_clanker(self, address: str) -> bool:
        """Vérifie si le token est sur Clanker"""
        try:
            url = f"https://www.clanker.world/api/tokens/{address}"
            async with self.session.get(url, timeout=5) as resp:
                return resp.status == 200
        except:
            return False
    
    async def _check_farcaster(self, address: str) -> bool:
        """Vérifie si le token est mentionné sur Farcaster"""
        # Ceci nécessiterait une API Farcaster
        return False
    
    async def _check_baseapp(self, address: str) -> bool:
        """Vérifie si le token est sur Base.app"""
        try:
            url = f"https://base.app/api/token/{address}"
            async with self.session.get(url, timeout=5) as resp:
                return resp.status == 200
        except:
            return False
    
    async def _check_uniswap(self, address: str, chain: str) -> bool:
        """Vérifie si le token a une pool Uniswap"""
        try:
            # Utilise l'API Uniswap v3 subgraph
            subgraph_urls = {
                "ethereum": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3",
                "base": "https://api.studio.thegraph.com/query/48211/uniswap-v3-base/version/latest",
            }
            
            if chain not in subgraph_urls:
                return False
            
            query = """
            {
              pools(where: {token0: "%s"}) {
                id
              }
            }
            """ % address.lower()
            
            async with self.session.post(
                subgraph_urls[chain],
                json={"query": query},
                timeout=10
            ) as resp:
                data = await resp.json()
                return len(data.get("data", {}).get("pools", [])) > 0
        except:
            return False
    
    async def search_social_mentions(self, ticker: str) -> List[str]:
        """Recherche les mentions du ticker sur les réseaux sociaux"""
        mentions = []
        
        # Recherche sur Twitter/X (nécessite API)
        # mentions.append(f"Twitter: recherche pour ${ticker}")
        
        # Recherche sur Farcaster
        # mentions.append(f"Farcaster: recherche pour ${ticker}")
        
        # Pour l'instant, retourne des URLs de recherche
        mentions.append(f"🔍 Twitter: https://twitter.com/search?q=%24{ticker}")
        mentions.append(f"🔍 Farcaster: https://warpcast.com/~/search?q=%24{ticker}")
        
        return mentions
    
    async def get_deployer_info(self, token_address: str, chain: str) -> Optional[str]:
        """Récupère l'adresse du déployeur du contrat"""
        try:
            api_urls = {
                "ethereum": f"https://api.etherscan.io/api?module=contract&action=getcontractcreation&contractaddresses={token_address}&apikey={ETHERSCAN_API_KEY}",
                "base": f"https://api.basescan.org/api?module=contract&action=getcontractcreation&contractaddresses={token_address}&apikey={BASESCAN_API_KEY}",
            }
            
            if chain not in api_urls:
                return None
            
            async with self.session.get(api_urls[chain], timeout=10) as resp:
                data = await resp.json()
                if data["status"] == "1" and data["result"]:
                    return data["result"][0]["contractCreator"]
        except Exception as e:
            print(f"Erreur get_deployer_info: {e}")
        
        return None
    
    async def get_deployer_tokens(self, deployer_address: str, chain: str, limit: int = 5) -> List[Dict]:
        """Récupère les tokens créés par le déployeur"""
        try:
            api_urls = {
                "ethereum": f"https://api.etherscan.io/api?module=account&action=txlist&address={deployer_address}&sort=desc&apikey={ETHERSCAN_API_KEY}",
                "base": f"https://api.basescan.org/api?module=account&action=txlist&address={deployer_address}&sort=desc&apikey={BASESCAN_API_KEY}",
            }
            
            if chain not in api_urls:
                return []
            
            async with self.session.get(api_urls[chain], timeout=10) as resp:
                data = await resp.json()
                
                if data["status"] != "1":
                    return []
                
                # Filtre les transactions de création de contrat
                created_tokens = []
                for tx in data["result"]:
                    if tx.get("to") == "" and tx.get("contractAddress"):
                        try:
                            token_info = await self.get_token_info(tx["contractAddress"], chain)
                            if "error" not in token_info:
                                created_tokens.append({
                                    "name": token_info["name"],
                                    "symbol": token_info["symbol"],
                                    "address": tx["contractAddress"],
                                    "timestamp": datetime.fromtimestamp(int(tx["timeStamp"])).strftime("%Y-%m-%d %H:%M:%S")
                                })
                                
                                if len(created_tokens) >= limit:
                                    break
                        except:
                            continue
                
                return created_tokens
        except Exception as e:
            print(f"Erreur get_deployer_tokens: {e}")
            return []
    
    async def get_funding_address(self, deployer_address: str, chain: str) -> Optional[str]:
        """Récupère l'adresse qui a financé le déployeur"""
        try:
            api_urls = {
                "ethereum": f"https://api.etherscan.io/api?module=account&action=txlist&address={deployer_address}&sort=asc&apikey={ETHERSCAN_API_KEY}",
                "base": f"https://api.basescan.org/api?module=account&action=txlist&address={deployer_address}&sort=asc&apikey={BASESCAN_API_KEY}",
            }
            
            if chain not in api_urls:
                return None
            
            async with self.session.get(api_urls[chain], timeout=10) as resp:
                data = await resp.json()
                
                if data["status"] == "1" and data["result"]:
                    # Prend la première transaction entrante
                    for tx in data["result"]:
                        if tx["to"].lower() == deployer_address.lower() and int(tx["value"]) > 0:
                            return tx["from"]
        except Exception as e:
            print(f"Erreur get_funding_address: {e}")
        
        return None
    
    async def analyze_token(self, address: str) -> str:
        """Analyse complète d'un token"""
        await self.init_session()
        
        result = "🔍 **ANALYSE DU TOKEN**\n\n"
        
        # Validation de l'adresse
        if not is_address(address):
            return "❌ Adresse de contrat invalide"
        
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
            result += f"• Decimals: {token_info['decimals']}\n\n"
            ticker = token_info['symbol']
        else:
            result += f"❌ Erreur: {token_info['error']}\n\n"
            ticker = "UNKNOWN"
        
        # Détection de la plateforme
        result += "🌐 **PLATEFORMES DÉTECTÉES**\n"
        platforms = await self.detect_platform(address, chain)
        if platforms["platforms"]:
            for platform in platforms["platforms"]:
                result += f"• {platform['name'].capitalize()}: {platform['url']}\n"
        else:
            result += "• Aucune plateforme spécifique détectée\n"
            result += f"• Uniswap: https://app.uniswap.org/explore/tokens/{chain}/{address}\n"
            result += f"• DEXScreener: https://dexscreener.com/{chain}/{address}\n"
        result += "\n"
        
        # Mentions sociales
        result += f"💬 **MENTIONS SOCIALES (${ticker})**\n"
        mentions = await self.search_social_mentions(ticker)
        for mention in mentions:
            result += f"• {mention}\n"
        result += "\n"
        
        # Analyse du déployeur
        result += "👤 **ANALYSE DU DÉPLOYEUR**\n"
        deployer = await self.get_deployer_info(address, chain)
        if deployer:
            result += f"• Adresse: `{deployer}`\n"
            
            # Tokens précédents du déployeur
            result += "\n📋 **Tokens créés par ce déployeur (max 5):**\n"
            deployer_tokens = await self.get_deployer_tokens(deployer, chain, 5)
            if deployer_tokens:
                for token in deployer_tokens:
                    result += f"  • {token['name']} (${token['symbol']}) - {token['timestamp']}\n"
                    result += f"    `{token['address']}`\n"
            else:
                result += "  • Aucun autre token trouvé ou données non disponibles\n"
            
            # Analyse du wallet de financement
            result += "\n💰 **WALLET DE FINANCEMENT**\n"
            funder = await self.get_funding_address(deployer, chain)
            if funder:
                result += f"• Adresse: `{funder}`\n"
                
                result += "\n📋 **Tokens créés par le wallet de financement (max 5):**\n"
                funder_tokens = await self.get_deployer_tokens(funder, chain, 5)
                if funder_tokens:
                    for token in funder_tokens:
                        result += f"  • {token['name']} (${token['symbol']}) - {token['timestamp']}\n"
                        result += f"    `{token['address']}`\n"
                else:
                    result += "  • Aucun token trouvé ou données non disponibles\n"
            else:
                result += "• Wallet de financement non trouvé\n"
        else:
            result += "• Informations du déployeur non disponibles\n"
        
        return result

# Handlers Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    welcome_message = """
🤖 **Bot d'Analyse de Tokens EVM**

Envoyez-moi simplement une adresse de contrat EVM et je vais analyser :

✅ Les informations du token
✅ La plateforme de création (Clanker, Uniswap, etc.)
✅ Les mentions sociales du ticker
✅ L'historique du déployeur
✅ Les tokens créés par le wallet de financement

**Exemple:**
`0x1234567890abcdef1234567890abcdef12345678`

**Configuration requise:**
- Variables d'environnement: TELEGRAM_BOT_TOKEN
- API keys: ETHERSCAN_API_KEY, BASESCAN_API_KEY, INFURA_KEY
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
    loading_msg = await update.message.reply_text("🔄 Analyse en cours... Cela peut prendre quelques secondes.")
    
    # Analyse
    analyzer = TokenAnalyzer()
    try:
        result = await analyzer.analyze_token(address)
        await loading_msg.edit_text(result, parse_mode="Markdown")
    except Exception as e:
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
    print("🤖 Bot démarré!")
    application.run_polling()

if __name__ == "__main__":
    main()