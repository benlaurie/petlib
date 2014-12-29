from petlib.ec import EcGroup, EcPt
from petlib.bn import Bn
from petlib.ecdsa import do_ecdsa_sign, do_ecdsa_verify
from petlib.cipher import Cipher
from petlib.encode import CryptoEnc, CryptoDec, B

from hashlib import sha1

import json
from os import urandom

# Cryptographic primitives used:
# - AES-128-GCM (IV=16, TAG=16).
# - ECDSA-SHA1 signature using NIST p224.
# - NIST p224 for key derivation.

def derive_2DH_sender(G, priv, pub1, pub2):
    md = sha1()
    md.update((priv * pub1).export())
    md.update((priv * pub2).export())
    return md.digest()

def derive_2DH_receiver(G, pub, priv1, priv2):
    md = sha1()
    md.update((priv1 * pub).export())
    md.update((priv2 * pub).export())
    return md.digest()


def derive_3DH_sender(G, priv1, priv2, pub1, pub2):
    md = sha1()
    md.update((priv1 * pub2).export())
    md.update((priv2 * pub1).export())
    md.update((priv2 * pub2).export())
    return md.digest()

def derive_3DH_receiver(G, pub1, pub2, priv1, priv2):
    md = sha1()
    md.update((priv2 * pub1).export())
    md.update((priv1 * pub2).export())
    md.update((priv2 * pub2).export())
    return md.digest()

## Define a "steady state" channel:
#  - Use a shared key for channel confidentiality and integrity.
#  - Use "ecdsa" for authenticaity (ephemeral)

class KulanClient(object):

    def __init__(self, G, name, priv, pki):
        # Maths
        self.G = G
        self.g = self.G.generator()
        self.order = self.G.order()

        ## Store keys
        self.priv = priv
        self.pub = priv * self.g

        self.pki = pki
        self.name = name

        # Which channel are we in?
        self.admins = []
        self.members = []

        # Channel key stores
        self.Ks = [] 

        ## Generate an ephemeral signature key
        self.priv_sign = self.order.random()
        self.pub_sign = self.priv_sign * self.g

        ## Storage for short term dictionaries
        self.current_dict = {"me": self.pub_sign}

        ## Generate an ephemeral signature key
        self.priv_enc = self.order.random()
        self.pub_enc = self.priv_enc * self.g

        self.aes = Cipher("aes-128-gcm")

    def broadcast_encrypt(self, plaintext):
        encode = CryptoEnc().encode

        sym_key = urandom(16)
        iv = urandom(16)

        msg = [self.pub, self.pub_enc, B(iv)]

        msg2 = []
        for name, (pub1, pub2) in self.pki.items():
            K = derive_3DH_sender(self.G, self.priv, self.priv_enc, pub1, pub2)            

            ciphertext, tag = self.aes.quick_gcm_enc(K[:16], iv, sym_key)
            msg2 += [(B(ciphertext), B(tag))]

        msg += [msg2]
        inner_msg = encode([B(self.name), self.pub_sign])
        
        ciphertext, tag = self.aes.quick_gcm_enc(sym_key, iv, inner_msg)
        msg += [(B(ciphertext), B(tag))]

        return encode(msg)

    def broadcast_decrypt(self, msgs):
        decode = CryptoDec().decode

        msgs = decode(msgs)
        pub1, pub2, iv = msgs[0:3]

        K = derive_3DH_receiver(self.G, pub1, pub2, self.priv, self.priv_enc)

        sym_key = None
        for cip, tag in msgs[3]:
            sym_key = self.aes.quick_gcm_dec(K[:16], iv, cip, tag)
            if sym_key:
                break

        ## Is no decryption is available bail-out
        if not sym_key:
            raise Exception("No decryption")

        ciphertext2, tag2 = msgs[-1] 
        plaintext = self.aes.quick_gcm_dec(sym_key, iv, ciphertext2, tag2)
        
        [name, sig_key] = decode(plaintext)
        
        if self.pki[name] == pub1:
            return (name, sig_key)
        return None
            

    def steady_encrypt(self, plaintext):
        assert len(self.Ks) > 0
        encode = CryptoEnc().encode

        ## Sign using ephemeral signature
        md = sha1(self.Ks[-1] + plaintext).digest()

        # Note: include the key here to bing the signature 
        # to the encrypted channel defined by this key. 
        r, s = do_ecdsa_sign(self.G, self.priv_sign, md)
        inner_message = [B(self.name), B(plaintext), r, s]
        plain_inner = encode(inner_message)
        
        ## Encrypt using AEC-GCM
        iv = urandom(16)
        ciphertext, tag = self.aes.quick_gcm_enc(self.Ks[-1], iv, 
                                                 plain_inner)
        
        return encode([B(iv), B(ciphertext), B(tag)])


    def steady_decrypt(self, ciphertext):
        assert len(self.Ks) > 0
        decode = CryptoDec().decode

        [iv, ciphertext, tag] = decode(ciphertext)

        ## Decrypt and check integrity
        plaintext = self.aes.quick_gcm_dec(self.Ks[-1], iv,
                                           ciphertext, tag)
        ## Check signature
        [xname, xplain, r, s] = decode(plaintext)
        md = sha1(self.Ks[-1] + str(xplain)).digest()
        
        sig = (r,s)
        pub = self.current_dict[str(xname)]
        if not do_ecdsa_verify(self.G, pub, sig, str(md)):
            return None

        return (xname, xplain)


## Define an "introduction message":
#  - Use 2DH to derive parwise shared keys.
#  - Use MACs to provide integirty and authenticity.

## Define client state
#  - Own long-term secret key.
#  - Own short-term secret key.
#  - Short-tem signature key.
#  - Link to name <-> key map.
#  - Map of names in the channel.

def test_steady():
    G = EcGroup()
    g = G.generator()
    x = G.order().random()
    pki = {"me":(x * g, x * g)}
    client = KulanClient(G, "me", x, pki)

    ## Mock some keys
    client.Ks += [urandom(16)]

    # Decrypt a small message
    ciphertext = client.steady_encrypt("Hello World!")
    client.steady_decrypt(ciphertext)

    # Decrypt a big message
    ciphertext = client.steady_encrypt("Hello World!"*10000)
    client.steady_decrypt(ciphertext)

    # decrypt an empty string
    ciphertext = client.steady_encrypt("")
    client.steady_decrypt(ciphertext)

    # Time it
    import time
    t0 = time.clock()
    for _ in range(1000):
        ciphertext = client.steady_encrypt("Hello World!"*10)
        client.steady_decrypt(ciphertext)
    t = time.clock() - t0

    print
    print " - %2.2f operations / sec" % (1.0 / (t / 1000))

def test_2DH():
    G = EcGroup()
    g = G.generator()
    o = G.order()

    priv1 = o.random()
    priv2 = o.random()
    priv3 = o.random()

    k1 = derive_2DH_sender(G, priv1, priv2 * g, priv3 * g)
    k2 = derive_2DH_receiver(G, priv1 * g, priv2, priv3)

    assert k1 == k2

def pair(G):
    x = G.order().random()
    gx = x * G.generator()
    return x, gx

def test_3DH():
    G = EcGroup()
    g = G.generator()
    o = G.order()

    priv1, pub1 = pair(G)
    priv2, pub2 = pair(G)
    priv3, pub3 = pair(G)
    priv4, pub4 = pair(G)

    k1 = derive_3DH_sender(G, priv1, priv2, pub3, pub4)
    k2 = derive_3DH_receiver(G, pub1, pub2, priv3, priv4)
    assert k1 == k2


def test_broad():
    G = EcGroup()
    g = G.generator()
    x = G.order().random()

    a, puba = pair(G)
    b, pubb = pair(G)
    c, pubc = pair(G)
    a2, puba2 = pair(G)
    b2, pubb2 = pair(G)
    c2, pubc2 = pair(G)

    pki = {"a":(puba,puba2) , "b":(pubb, pubb2), "c":(pubc, pubc2)}
    client = KulanClient(G, "me", x, pki)

    msgs = client.broadcast_encrypt("Hello!")

    pki2 = {"me": x * g, "b":(pubb, pubb2), "c":(pubc, pubc2)}
    dec_client = KulanClient(G, "a", a, pki2)

    dec_client.priv_enc = a2
    dec_client.pub_enc = puba2

    namex, keysx = dec_client.broadcast_decrypt(msgs)
    assert namex == "me"
    # print msgs