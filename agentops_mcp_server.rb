class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/09/b5/3e9908fc7fad150491ecbb42fd70bcba1162a59735c81783ac9f5f4fb077/agentops_mcp_server-0.1.7.tar.gz"
  sha256 "c2c644084a6481a18990f7dc277ce0ddf36b530dfa6ee273a091885fc1ecde49"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
